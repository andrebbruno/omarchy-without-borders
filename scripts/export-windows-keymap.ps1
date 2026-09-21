# Exporta a tabela VK -> scancode do layout de teclado ativo no Windows.
# Uso (no Windows):  powershell -File export-windows-keymap.ps1 > keymap.txt
# Depois, no Linux:  owb import-keymap keymap.txt
$src = @'
using System; using System.Runtime.InteropServices; using System.Text;
public static class KL {
  [DllImport("user32.dll")] public static extern uint MapVirtualKeyEx(uint uCode, uint uMapType, IntPtr dwhkl);
  [DllImport("user32.dll")] public static extern IntPtr GetKeyboardLayout(uint idThread);
  [DllImport("user32.dll")] public static extern bool GetKeyboardLayoutName(StringBuilder pwszKLID);
}
'@
Add-Type -TypeDefinition $src
$hkl = [KL]::GetKeyboardLayout(0)
$sb = New-Object System.Text.StringBuilder 16
[KL]::GetKeyboardLayoutName($sb) | Out-Null
"# layout $($sb.ToString())"
foreach ($vk in 1..254) { $sc = [KL]::MapVirtualKeyEx([uint32]$vk, 0, $hkl); if ($sc -ne 0) { "$vk,$sc" } }
