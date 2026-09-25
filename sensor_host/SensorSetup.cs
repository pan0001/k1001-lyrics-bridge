// SPDX-License-Identifier: GPL-3.0-only
// Explicitly elevated setup only. Protected binaries, fixed task action, no saved passwords.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;

internal static class SensorSetup {
    static string Hash(string path) {
        using (var sha = SHA256.Create()) using (var stream = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }
    static void Protect(string path, SecurityIdentifier sid) {
        if (Directory.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("Reparse installation directory rejected");
        Directory.CreateDirectory(path);
        var acl = new DirectorySecurity();
        acl.SetAccessRuleProtection(true, false);
        var admin = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
        acl.SetOwner(admin);
        foreach (var id in new[] { admin, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null) })
            acl.AddAccessRule(new FileSystemAccessRule(id, FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.ReadAndExecute,
            InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        Directory.SetAccessControl(path, acl);
    }
    [STAThread]
    static int Main(string[] args) {
        if (args.Length != 2 || (args[0] != "install" && args[0] != "remove")) return 2;
        try {
            var sid = new SecurityIdentifier(args[1]);
            if (!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) return 5;
            string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "SkyLyrics Sensors");
            string userRoot = Path.Combine(root, sid.Value);
            string name = "SkyLyricsSensors-" + sid.Value;
            dynamic scheduler = Activator.CreateInstance(Type.GetTypeFromProgID("Schedule.Service"));
            scheduler.Connect();
            dynamic folder = scheduler.GetFolder("\\");
            if (args[0] == "remove") {
                try { folder.GetTask(name).Stop(0); folder.DeleteTask(name, 0); }
                catch (Exception ex) {
                    if ((uint)ex.HResult != 0x80070002) throw;
                }
                string marker = Path.Combine(userRoot, "current.txt");
                if (File.Exists(marker)) File.Delete(marker);
                return 0;
            }
            string source = AppDomain.CurrentDomain.BaseDirectory;
            var files = new Dictionary<string, string>();
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("sensor-files.txt"))
            using (var reader = new StreamReader(stream)) {
                while (!reader.EndOfStream) {
                    string[] parts = reader.ReadLine().Split(new[] { ' ' }, 2);
                    if (parts.Length != 2 || Path.GetFileName(parts[1]) != parts[1]) throw new IOException("Invalid manifest");
                    if (Hash(Path.Combine(source, parts[1])) != parts[0]) throw new IOException("Sensor files have changed");
                    files.Add(parts[1], parts[0]);
                }
            }
            Protect(root, new SecurityIdentifier(WellKnownSidType.BuiltinUsersSid, null)); Protect(userRoot, sid);
            // New immutable version directory avoids replacing a running elevated DLL.
            string version = Hash(Assembly.GetExecutingAssembly().Location).Substring(0, 16);
            string destination = Path.Combine(userRoot, version);
            Protect(destination, sid);
            foreach (var file in files) {
                string target = Path.Combine(destination, file.Key);
                if (File.Exists(target)) {
                    if ((File.GetAttributes(target) & FileAttributes.ReparsePoint) != 0 || Hash(target) != file.Value)
                        throw new IOException("Unexpected installed file");
                } else File.Copy(Path.Combine(source, file.Key), target);
                if (Hash(target) != file.Value) throw new IOException("Copy checksum mismatch");
            }
            string executable = Path.Combine(destination, "SkyLyricsSensors.exe");
            dynamic task = scheduler.NewTask(0);
            task.RegistrationInfo.Description = "SkyLyrics CPU temperature. Reads on demand after this user logs in; no UI or password storage.";
            task.Principal.UserId = sid.Value;
            task.Principal.LogonType = 3; // InteractiveToken: no password saved.
            task.Principal.RunLevel = 1;
            task.Settings.Enabled = true;
            task.Settings.AllowDemandStart = true;
            task.Settings.StartWhenAvailable = true;
            task.Settings.DisallowStartIfOnBatteries = false;
            task.Settings.StopIfGoingOnBatteries = false;
            task.Settings.ExecutionTimeLimit = "PT0S";
            task.Settings.MultipleInstances = 2;
            task.Settings.RestartInterval = "PT1M";
            task.Settings.RestartCount = 3;
            dynamic trigger = task.Triggers.Create(9);
            trigger.UserId = sid.Value; trigger.Delay = "PT5S";
            dynamic action = task.Actions.Create(0);
            action.Path = executable;
            action.Arguments = "--persistent " + sid.Value;
            action.WorkingDirectory = destination;
            // The normal user can read/run the task, but cannot change its elevated command.
            string sddl = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;" + sid.Value + ")";
            try { folder.GetTask(name).Stop(0); }
            catch (Exception ex) {
                // COM HRESULT 0x80070002 is mapped to FileNotFoundException by .NET.
                // A first-time install has no previous task to stop.
                if ((uint)ex.HResult != 0x80070002) throw;
            }
            dynamic registered = folder.RegisterTaskDefinition(name, task, 6 | 16, sid.Value, null, 3, sddl);
            string markerPath = Path.Combine(userRoot, "current.txt");
            if (File.Exists(markerPath) && (File.GetAttributes(markerPath) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Unexpected installation marker");
            File.WriteAllText(markerPath, version, Encoding.ASCII);
            registered.Run(null);
            return 0;
        } catch (Exception ex) {
            // Numeric failure visible to caller; do not write privileged files to caller-supplied paths.
            System.Windows.Forms.MessageBox.Show("CPU 温度自动启动配置失败：\n" + ex.Message,
                "晴空歌词 · 温度采集", System.Windows.Forms.MessageBoxButtons.OK, System.Windows.Forms.MessageBoxIcon.Error);
            return 1;
        }
    }
}
