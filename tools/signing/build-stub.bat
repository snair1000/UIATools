@echo off
REM Builds UIATools-CertStub.exe - a tiny (~5 KB) PE file whose only purpose
REM is to be signed with the same certificate as UIATools.exe and handed to
REM IT for CrowdStrike IOC certificate exclusions.
REM Uses the C# compiler bundled with Windows (.NET Framework) - no SDK needed.

setlocal
cd /d "%~dp0"

set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
    echo ERROR: csc.exe not found. .NET Framework 4.x is required.
    exit /b 1
)

"%CSC%" /nologo /optimize /target:exe /out:UIATools-CertStub.exe stub.cs
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

for %%A in (UIATools-CertStub.exe) do echo Built UIATools-CertStub.exe (%%~zA bytes)
echo Next: sign it together with dist\UIATools.exe using tools\signing\sign.ps1
endlocal
