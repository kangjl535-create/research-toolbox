# OCR page images with the OCR engine built into Windows (Windows.Media.Ocr, en-US); local only, no download.
# usage: powershell -File ocr_windows.ps1 <png dir> <out json>
# Output: [{page, width, height, angle, lines:[{text, words:[{text, x, y, w, h}]}]}] in image pixels.
param([string]$PngDir, [string]$OutJson)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("en-US"))
$pages = @()
foreach ($f in Get-ChildItem -Path $PngDir -Filter "p*.png" | Sort-Object { [int]($_.BaseName.Substring(1)) }) {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($l in $res.Lines) {
        $words = @($l.Words | ForEach-Object { [ordered]@{ text = $_.Text; x = $_.BoundingRect.X; y = $_.BoundingRect.Y; w = $_.BoundingRect.Width; h = $_.BoundingRect.Height } })
        $lines += [ordered]@{ text = $l.Text; words = $words }
    }
    $pages += [ordered]@{ page = [int]($f.BaseName.Substring(1)); width = $bmp.PixelWidth; height = $bmp.PixelHeight; angle = $res.TextAngle; lines = $lines }
    $stream.Dispose()
}
[System.IO.File]::WriteAllText($OutJson, (ConvertTo-Json $pages -Depth 6 -Compress), (New-Object System.Text.UTF8Encoding $false))
"pages: " + $pages.Count + "; lines: " + ($pages | ForEach-Object { $_.lines.Count } | Measure-Object -Sum).Sum
