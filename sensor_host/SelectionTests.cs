using System;
class SelectionTests {
    static void Main() {
        var selected = TemperatureSelection.Select(new[] {
            new Reading("Core (Tctl/Tdie)", 65), new Reading("CCDs Max (Tdie)", 80),
            new Reading("CCD1 (Tdie)", 70) });
        if (selected != 65) throw new Exception("AMD package preference failed");
        selected = TemperatureSelection.Select(new[] {
            new Reading("CPU Core #1", 80), new Reading("CPU Package", 66) });
        if (selected != 66) throw new Exception("Intel package preference failed");
        selected = TemperatureSelection.Select(new[] {
            new Reading("CPU Package", Double.NaN), new Reading("Core #1", 0),
            new Reading("Core #2", 130), new Reading("Core #3", Double.PositiveInfinity) });
        if (selected.HasValue) throw new Exception("Invalid temperatures accepted");
        Console.WriteLine("3 sensor selection checks passed");
    }
}
