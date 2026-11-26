# Renders the WAVIoT mark into the brand images Home Assistant expects.
# Usage: pwsh -File assets/render-logo.ps1
param(
    [string]$Color = "#1B6EA5",
    [string]$DarkColor = "#FFFFFF"
)

Add-Type -AssemblyName System.Drawing

# Bounding box of the artwork in the 1023x1023 vector space (assets/waviot.svg):
# x 200..930, y 30..800. The canvas is scaled so the artwork is trimmed -
# only ~5% transparent padding stays on the short side.
$BoxX = 200.0
$BoxW = 730.0
$BoxY = 30.0
$BoxH = 770.0

function New-Logo([int]$size, [System.Drawing.Color]$color) {
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)

    # Fit the artwork into the square canvas, centred, no dead margins.
    $scale = [Math]::Min($size / $BoxW, $size / $BoxH)
    $g.ScaleTransform($scale, $scale)
    $g.TranslateTransform(
        ($size / $scale - $BoxW) / 2 - $BoxX,
        ($size / $scale - $BoxH) / 2 - $BoxY
    )

    $brush = New-Object System.Drawing.SolidBrush $color

    # Meter body (rounded rect) with the display window as a hole.
    $body = New-Object System.Drawing.Drawing2D.GraphicsPath
    $body.FillMode = [System.Drawing.Drawing2D.FillMode]::Alternate
    $body.AddArc(200, 300, 120, 120, 180, 90)
    $body.AddArc(600, 300, 120, 120, 270, 90)
    $body.AddArc(600, 700, 120, 120, 0, 90)
    $body.AddArc(200, 700, 120, 120, 90, 90)
    $body.CloseFigure()
    $body.AddRectangle([System.Drawing.Rectangle]::New(260, 340, 340, 200))
    $g.FillPath($brush, $body)

    # Lightning bolt inside the display window.
    $bolt = New-Object System.Drawing.Drawing2D.GraphicsPath
    $bolt.AddPolygon([System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::New(460, 340),
        [System.Drawing.PointF]::New(360, 450),
        [System.Drawing.PointF]::New(425, 450),
        [System.Drawing.PointF]::New(400, 520),
        [System.Drawing.PointF]::New(520, 400),
        [System.Drawing.PointF]::New(455, 400),
        [System.Drawing.PointF]::New(500, 340)
    ))
    $g.FillPath($brush, $bolt)

    # Radio waves from the meter to the cabinet.
    $pen = New-Object System.Drawing.Pen -ArgumentList $color, 42
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    foreach ($r in 120, 195, 270) {
        $arc = New-Object System.Drawing.Drawing2D.GraphicsPath
        $arc.AddArc(660 - $r, 300 - $r, 2 * $r, 2 * $r, 0, -90)
        $g.DrawPath($pen, $arc)
        $arc.Dispose()
    }

    $g.Dispose()
    $brush.Dispose()
    $pen.Dispose()
    return $bmp
}

function Convert-Color([string]$hex) {
    $hex = $hex.TrimStart('#')
    return [System.Drawing.Color]::FromArgb(
        255,
        [Convert]::ToInt32($hex.Substring(0, 2), 16),
        [Convert]::ToInt32($hex.Substring(2, 2), 16),
        [Convert]::ToInt32($hex.Substring(4, 2), 16)
    )
}

function Save-Logo([int]$size, [System.Drawing.Color]$color, [string]$path) {
    $bmp = New-Logo $size $color
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
}

$brand = Join-Path $PSScriptRoot '..\custom_components\waviot\brand'
New-Item -ItemType Directory -Force -Path $brand | Out-Null

$c = Convert-Color $Color
$d = Convert-Color $DarkColor

# Home Assistant brand images (square icon, 1:1, transparent, trimmed).
Save-Logo 256 $c (Join-Path $brand 'icon.png')
Save-Logo 512 $c (Join-Path $brand 'icon@2x.png')
Save-Logo 256 $d (Join-Path $brand 'dark_icon.png')
Save-Logo 512 $d (Join-Path $brand 'dark_icon@2x.png')

# Extra copies for the README and for a home-assistant/brands PR.
Save-Logo 512 $c (Join-Path $PSScriptRoot 'waviot.png')
Save-Logo 128 $c (Join-Path $PSScriptRoot 'waviot-128.png')
Save-Logo 512 ([System.Drawing.Color]::FromArgb(255, 0, 0, 0)) (Join-Path $PSScriptRoot 'waviot-mono.png')

Write-Output 'rendered: custom_components/waviot/brand/{icon.png,icon@2x.png,dark_icon.png,dark_icon@2x.png} + assets copies'
