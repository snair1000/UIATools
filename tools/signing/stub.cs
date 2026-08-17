// Tiny stub PE for CrowdStrike certificate extraction.
// This exe does nothing useful - it exists only to be signed with the same
// code-signing certificate as UIATools.exe, so IT can load it into
// CrowdStrike IOC certificate exclusions (the real exe is too large >32MB).
// Build with build-stub.bat (uses the C# compiler that ships with Windows).

using System;

internal static class Program
{
    private static void Main()
    {
        Console.WriteLine("UIATools certificate stub. This file exists only to carry the code-signing certificate.");
    }
}
