<#
    WCPA Shorts — Windows SAPI5 text-to-speech helper.

    Synthesises a narration WAV from a UTF-8 text file using the built-in
    System.Speech engine (no third-party dependency). Called by
    tools/shorts_voice.py; not meant to be run by hand.

    Plain text is spoken via .Speak(); text beginning with "<speak" is
    treated as SSML and spoken via .SpeakSsml().

    Usage:
      powershell -ExecutionPolicy Bypass -File shorts_tts.ps1 `
          -TextPath in.txt -WavPath out.wav -Voice "Microsoft Hazel Desktop" -Rate -1
#>
param(
    [Parameter(Mandatory = $true)] [string] $TextPath,
    [Parameter(Mandatory = $true)] [string] $WavPath,
    [string] $Voice = "",
    [int]    $Rate  = 0,
    [int]    $Volume = 100
)

$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

    if ($Voice -ne "") {
        try { $synth.SelectVoice($Voice) }
        catch { Write-Warning "voice '$Voice' unavailable; using default" }
    }

    $synth.Rate   = [Math]::Max(-10, [Math]::Min(10, $Rate))
    $synth.Volume = [Math]::Max(0, [Math]::Min(100, $Volume))

    $synth.SetOutputToWaveFile($WavPath)
    $text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)

    if ($text.TrimStart().StartsWith("<speak")) {
        $synth.SpeakSsml($text)
    } else {
        $synth.Speak($text)
    }

    $synth.SetOutputToNull()
    $synth.Dispose()
    Write-Output "OK"
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
