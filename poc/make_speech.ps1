# Writes a Japanese TTS reading to a 48kHz 16bit mono WAV.
param([string]$OutPath, [string]$TextPath)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Haruka Desktop")
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile($OutPath, $format)
$synth.Speak([System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8))
$synth.Dispose()
Write-Output "written $OutPath"
