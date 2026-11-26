' 农知行智慧农业平台 开机自启动（登录时静默运行）
Set sh = CreateObject("WScript.Shell")
desktop = sh.SpecialFolders("Desktop")
ps1 = desktop & "\农知行智慧农业平台\nongzhixing\启动项目.ps1"
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """", 0, False
