// SPDX-License-Identifier: GPL-3.0-only
// CPU-only, on-demand sensor worker. No hardware writes or RPC shell.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using LibreHardwareMonitor.Hardware;

internal struct Reading {
    public string Name;
    public double Value;
    public Reading(string name, double value) { Name = name; Value = value; }
}

internal static class TemperatureSelection {
    public static double? Select(IEnumerable<Reading> readings) {
        int bestRank = -1;
        double? best = null;
        foreach (var reading in readings) {
            double v = reading.Value;
            if (Double.IsNaN(v) || Double.IsInfinity(v) || v <= 0 || v >= 130) continue;
            string name = reading.Name.ToLowerInvariant();
            int rank = name.Contains("tctl") || name.Contains("package") ? 3 :
                name.Contains("tdie") && !name.Contains("ccd") ? 2 : 1;
            if (rank > bestRank || rank == bestRank && (!best.HasValue || v > best.Value)) {
                bestRank = rank;
                best = v;
            }
        }
        return best;
    }
}

internal static class SensorHost {
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetNamedPipeClientProcessId(IntPtr pipe, out uint pid);
    static Computer computer;
    static readonly object hardwareLock = new object();
    static long lastRequest = Stopwatch.GetTimestamp();
    static long sampleStarted;
    static int stopped;
    static string cachedSample;
    static long cachedAt;

    static double SecondsSince(long ticks) {
        return (Stopwatch.GetTimestamp() - ticks) / (double)Stopwatch.Frequency;
    }
    static void CloseComputer() {
        if (computer != null) {
            try { computer.Close(); } catch { }
            computer = null;
        }
    }
    static string Sample() {
        if (!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))
            return "{\"status\":\"permission\"}";
        if (!LibreHardwareMonitor.PawnIo.PawnIo.IsInstalled)
            return "{\"status\":\"missing_driver\"}";
        lock (hardwareLock) {
            if (cachedSample != null && SecondsSince(cachedAt) < 1) return cachedSample;
            Interlocked.Exchange(ref sampleStarted, Stopwatch.GetTimestamp());
            try {
                if (computer == null) {
                    computer = new Computer { IsCpuEnabled = true };
                    computer.Open();
                }
                double? temperature = null;
                foreach (IHardware hardware in computer.Hardware) {
                    if (hardware.HardwareType != HardwareType.Cpu) continue;
                    hardware.Update();
                    var readings = new List<Reading>();
                    foreach (ISensor sensor in hardware.Sensors)
                        if (sensor.SensorType == SensorType.Temperature && sensor.Value.HasValue)
                            readings.Add(new Reading(sensor.Name, sensor.Value.Value));
                    double? candidate = TemperatureSelection.Select(readings);
                    if (candidate.HasValue && (!temperature.HasValue || candidate.Value > temperature.Value))
                        temperature = candidate;
                }
                cachedSample = temperature.HasValue
                    ? "{\"status\":\"ready\",\"cpu_temp\":" + Math.Round(temperature.Value, 1).ToString(CultureInfo.InvariantCulture) + "}"
                    : "{\"status\":\"unavailable\"}";
                cachedAt = Stopwatch.GetTimestamp();
                return cachedSample;
            } catch {
                CloseComputer();
                return "{\"status\":\"error\"}";
            } finally {
                Interlocked.Exchange(ref sampleStarted, 0);
            }
        }
    }

    [STAThread]
    static int Main(string[] args) {
        if (args.Length == 2 && args[0] == "--persistent") return RunPersistent(args[1]);
        int parentId;
        if (args.Length != 2 || !Regex.IsMatch(args[0], "\\A[a-f0-9]{32}\\z") ||
            !Int32.TryParse(args[1], out parentId)) return 2;
        try {
            using (Process parent = Process.GetProcessById(parentId)) {
                // Keep the original parent handle: a reused PID must not keep this worker alive.
                IntPtr parentHandle = parent.Handle;
                var security = new PipeSecurity();
                security.SetAccessRuleProtection(true, false);
                security.AddAccessRule(new PipeAccessRule(WindowsIdentity.GetCurrent().User,
                    PipeAccessRights.FullControl, AccessControlType.Allow));
                using (var pipe = new NamedPipeServerStream("SkyLyricsSensors-" + args[0],
                    PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous,
                    4096, 4096, security))
                using (var monitor = new Timer(delegate {
                    if (Volatile.Read(ref stopped) != 0) return;
                    try { if (parent.HasExited) Environment.Exit(0); } catch { Environment.Exit(0); }
                    long started = Interlocked.Read(ref sampleStarted);
                    if (started != 0 && SecondsSince(started) > 20) Environment.Exit(4);
                    // No hardware polling while the lyrics UI/idle display does not need data.
                    if (SecondsSince(Interlocked.Read(ref lastRequest)) > 20 && Monitor.TryEnter(hardwareLock)) {
                        try { CloseComputer(); } finally { Monitor.Exit(hardwareLock); }
                    }
                }, null, 3000, 3000)) {
                    var connection = pipe.BeginWaitForConnection(null, null);
                    if (!connection.AsyncWaitHandle.WaitOne(15000)) return 3;
                    pipe.EndWaitForConnection(connection);
                    uint clientId;
                    if (!GetNamedPipeClientProcessId(pipe.SafePipeHandle.DangerousGetHandle(), out clientId) || clientId != parentId)
                        return 5;
                    // Fixed one-byte protocol prevents unbounded requests or arbitrary privileged operations.
                    while (true) {
                        int command = pipe.ReadByte();
                        if (command < 0 || command == 'Q') break;
                        if (command != 'S') break;
                        Interlocked.Exchange(ref lastRequest, Stopwatch.GetTimestamp());
                        byte[] data = Encoding.ASCII.GetBytes(Sample() + "\n");
                        pipe.Write(data, 0, data.Length);
                        pipe.Flush();
                    }
                }
            }
            return 0;
        } catch { return 1; }
        finally {
            Volatile.Write(ref stopped, 1);
            lock (hardwareLock) { CloseComputer(); }
        }
    }

    static int RunPersistent(string userSid) {
        try {
            var sid = new SecurityIdentifier(userSid);
            // This task runs in the authorized user's interactive logon session.
            if (!sid.Equals(WindowsIdentity.GetCurrent().User)) return 6;
            var security = new PipeSecurity();
            security.SetAccessRuleProtection(true, false);
            security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.NetworkSid, null),
                PipeAccessRights.FullControl, AccessControlType.Deny));
            security.AddAccessRule(new PipeAccessRule(sid, PipeAccessRights.FullControl, AccessControlType.Allow));
            using (var monitor = new Timer(delegate {
                if (Volatile.Read(ref stopped) != 0) return;
                long started = Interlocked.Read(ref sampleStarted);
                if (started != 0 && SecondsSince(started) > 20) Environment.Exit(4);
                if (SecondsSince(Interlocked.Read(ref lastRequest)) > 20 && Monitor.TryEnter(hardwareLock)) {
                    try { CloseComputer(); } finally { Monitor.Exit(hardwareLock); }
                }
            }, null, 3000, 3000)) {
                while (true) {
                    // One bounded request per connection; reconnecting apps do not need UAC.
                    using (var pipe = new NamedPipeServerStream("SkyLyricsSensors-Auto-" + sid.Value,
                        PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous,
                        4096, 4096, security)) {
                        pipe.WaitForConnection();
                        try {
                            byte[] command = new byte[1];
                            var read = pipe.BeginRead(command, 0, 1, null, null);
                            using (read.AsyncWaitHandle) {
                                if (!read.AsyncWaitHandle.WaitOne(3000)) continue;
                                if (pipe.EndRead(read) != 1 || command[0] != 'S') continue;
                            }
                            Interlocked.Exchange(ref lastRequest, Stopwatch.GetTimestamp());
                            byte[] data = Encoding.ASCII.GetBytes(Sample() + "\n");
                            var write = pipe.BeginWrite(data, 0, data.Length, null, null);
                            using (write.AsyncWaitHandle) {
                                if (!write.AsyncWaitHandle.WaitOne(3000)) continue;
                                pipe.EndWrite(write);
                            }
                        } catch (IOException) { }
                    }
                }
            }
        } catch { return 1; }
        finally {
            Volatile.Write(ref stopped, 1);
            lock (hardwareLock) { CloseComputer(); }
        }
    }
}
