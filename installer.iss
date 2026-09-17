; Key 用量面板 — Inno Setup 安装脚本
; 用户级安装（免管理员），一次安装即用，无需 Python 等任何前置软件。

#define AppName "Key 用量面板"
#define AppExeName "key-usage-widget.exe"
; 版本号与 keymon/config.py 的 APP_VERSION 保持一致
#define AppVersion "1.0.0"
#define AppPublisher "Ming"

[Setup]
AppId={{8F3E5A1B-7C2D-4E6F-9A1B-2C3D4E5F6A7B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; 用户级安装目录：%LOCALAPPDATA%\Programs\key-usage-widget
DefaultDirName={localappdata}\Programs\key-usage-widget
DefaultGroupName={#AppName}
; 免管理员
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=KeyUsageWidget-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 「设置→应用」里显示的图标
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
; 安装/卸载前若应用在运行则提示关闭（静默模式下自动关闭）
CloseApplications=yes
CloseApplicationsFilter={#AppExeName}
RestartApplications=no
; 静默安装时也走用户级（否则静默模式默认提权装到 Program Files）
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesInstallIn64BitMode=x64compatible

; 官方 Inno 6.7.3 不内置简体中文语言包（需另行下载），用默认英文向导；
; 任务描述与卸载询问在脚本内直接写中文。
;[Languages]

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 (Create a desktop shortcut)"; GroupDescription: "附加任务 (Additional tasks)："; Flags: unchecked
Name: "autostart"; Description: "开机自启动 (Run at Windows startup)"; GroupDescription: "附加任务 (Additional tasks)："; Flags: unchecked

[Messages]
; 应用名含 CJK 时部分向导页标题在 ANSI 代码页下乱码，强制覆盖为英文
WizardSetup=Setup - Key Usage Widget
WelcomeLabel1=Welcome to the Key Usage Widget Setup Wizard
FinishedHeadingLabel=Completing the Key Usage Widget Setup Wizard

[Files]
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; 安装向导勾选的"开机自启"与托盘勾选写同一个 Run 项（单一事实来源）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "key-usage-widget"; ValueData: """{app}\{#AppExeName}"""; \
  Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "运行 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理注册表自启项（无论是否勾选过，确保无残留）
Type: filesandordirs; Name: "{app}"

[Code]
// 卸载时询问是否删除用户配置目录 %LOCALAPPDATA%\key-usage-widget
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ConfigDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    ConfigDir := ExpandConstant('{localappdata}\key-usage-widget');
    if DirExists(ConfigDir) then
    begin
      if MsgBox('Also delete configuration data (window position, etc.)?' + #13#10 + ConfigDir,
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(ConfigDir, True, True, True);
      end;
    end;
  end;
end;
