# autoblog 새 PC 설치 스크립트 (Windows 10/11). 여러 번 실행해도 안전(이미 된 것은 건너뜀).
#
# 사용법: install.bat 더블클릭, 또는
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Dir C:\경로\autoblog] [-WithChromium]
#
# 하는 일: Git / Python 3.12 / Chrome 설치 → 저장소 clone 또는 pull(공개 저장소, 로그인 불필요) →
#          파이썬 패키지 설치 → config.yaml 생성 → 폴더 준비
param(
    [string]$Dir = "$env:USERPROFILE\dev\autoblog",
    [string]$Repo = "https://github.com/infinit-steam/autoblog.git",
    [switch]$WithChromium   # Chrome 대신 Playwright 내장 Chromium 도 설치 (약 300MB, 보통 불필요)
)
# 네이티브 명령의 stderr 를 오류로 취급하지 않도록 Continue 로 두고 종료코드를 직접 확인한다.
$ErrorActionPreference = "Continue"

function Say($m)  { Write-Host "[설치] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  OK  $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[오류] $m" -ForegroundColor Red; exit 1 }
function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u;C:\Program Files\Git\cmd"
}
function Has($n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
function Winget-Install($id) {
    winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Fail "winget 설치 실패: $id (종료코드 $LASTEXITCODE)" }
    Refresh-Path
}
function Find-Python {
    # Microsoft Store 스텁(python.exe 만 있고 실제 설치 없음)을 걸러내려고 실제 실행해 버전을 확인한다.
    $cands = @()
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    $cands += Get-ChildItem "C:\Program Files\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    $cands += "python"
    foreach ($c in $cands) {
        $v = & $c --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) {
            return (Get-Command $c -ErrorAction SilentlyContinue).Source
        }
    }
    return $null
}

Write-Host "`n=== autoblog 설치 ===  설치 위치: $Dir`n"
Refresh-Path

# 0) winget
if (-not (Has winget)) { Fail "winget 이 없습니다. Microsoft Store 에서 'App Installer' 를 설치/업데이트한 뒤 다시 실행하세요." }

# 1) Git
Say "Git 확인"
if (-not (Has git)) { Winget-Install "Git.Git" }
if (-not (Has git)) { Fail "Git 설치 후에도 git 을 찾지 못했습니다. 새 터미널에서 다시 실행하세요." }
Ok (git --version)

# 3) Python 3.10+
Say "Python 확인"
$py = Find-Python
if (-not $py) { Winget-Install "Python.Python.3.12"; $py = Find-Python }
if (-not $py) { Fail "Python 3.10+ 를 찾지 못했습니다. 새 터미널에서 다시 실행하세요." }
Ok "$(& $py --version)  ($py)"

# 4) Chrome (기본 브라우저 방식에서 사용)
Say "Chrome 확인"
$chrome = @("C:\Program Files\Google\Chrome\Application\chrome.exe",
            "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { Winget-Install "Google.Chrome" }
Ok "Chrome 준비됨"

# 6) 저장소 clone / pull
Say "저장소 준비"
if (Test-Path (Join-Path $Dir ".git")) {
    git -C $Dir pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Host "  [주의] pull 실패(로컬 변경이 있을 수 있음). 코드 업데이트는 건너뜁니다." -ForegroundColor Yellow }
    else { Ok "최신 코드로 업데이트" }
} else {
    if ((Test-Path $Dir) -and (Get-ChildItem $Dir -Force | Select-Object -First 1)) { Fail "$Dir 가 비어 있지 않습니다. -Dir 로 다른 위치를 지정하세요." }
    New-Item -ItemType Directory -Force (Split-Path $Dir -Parent) | Out-Null
    git clone $Repo $Dir
    if ($LASTEXITCODE -ne 0) { Fail "clone 실패. 인터넷 연결과 저장소 주소($Repo)를 확인하세요. 저장소가 비공개 상태이면 공개로 전환해야 합니다." }
    Ok "clone 완료"
}

# 7) 파이썬 패키지
Say "파이썬 패키지 설치"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r (Join-Path $Dir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "pip install 실패" }
if ($WithChromium) { & $py -m playwright install chromium }
Ok "패키지 설치 완료"

# 8) 설정/폴더 준비
Say "설정 파일과 폴더 준비"
$cfg = Join-Path $Dir "config.yaml"
if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $Dir "config.example.yaml") $cfg
    Ok "config.yaml 생성 (예시 복사 - 계정 정보를 직접 수정해야 함)"
} else { Ok "config.yaml 이미 있음 (유지)" }
foreach ($d in "logs", "content", "profiles") { New-Item -ItemType Directory -Force (Join-Path $Dir $d) | Out-Null }

# 9) 동작 확인 (브라우저를 띄우지 않는 import 점검)
Say "동작 점검"
Push-Location $Dir
& $py -c "import playwright, requests, yaml, customtkinter, PIL, anthropic, main, platforms; print('import OK')"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "모듈 import 점검 실패" }

Write-Host "`n=== 설치 완료 ===" -ForegroundColor Green
Write-Host @"

다음 단계 (이 PC 에서 1회):
  1) 설정 수정:   notepad $cfg
       - accounts: name(예: acc1) / blog_id(비워 두면 로그인한 계정의 블로그를 자동 사용)
       - ai.api_key: AI 글 작성을 쓸 때 (환경변수 ANTHROPIC_API_KEY 로 대신해도 됨)
  2) 로그인(플랫폼마다 1회, 이 PC 에서 쓸 계정으로):
       login.bat 더블클릭  (계정 이름을 묻고 네이버·인스타·스레드 로그인 창을 차례로 열어 줍니다)
       또는 gui.bat 실행 후 왼쪽 아래 '로그인' 버튼
       ('로그인 상태 유지' 체크, 보안 확인이 나오면 끝까지 완료)
  3) 실행:        gui.bat 더블클릭 (먼저 dry-run 으로 확인)
  4) 글 준비:     content\README.md 참고 (GUI 에서 주제를 만들고 글/사진 작성)

업데이트: install.bat 을 다시 실행하면 최신 코드로 갱신됩니다 (config.yaml / content / profiles 는 유지).
참고: 방금 설치한 Python 이 인식되지 않으면 PC 를 다시 로그인(또는 재부팅)한 뒤 gui.bat 을 실행하세요.
"@
