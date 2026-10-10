$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose a local video for ERMCLIP'
$dialog.Filter = 'Video files|*.mp4;*.mkv;*.mov;*.webm;*.avi;*.m4v'
$dialog.Multiselect = $false
$dialog.CheckFileExists = $true
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.Width = 1
$owner.Height = 1
$owner.Show()
try {
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        Write-Output $dialog.FileName
    }
} finally {
    $dialog.Dispose()
    $owner.Dispose()
}
