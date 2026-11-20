"""
uwp_detector.py
------------------
Detecta apps empaquetadas (UWP / Microsoft Store) que shortcut_scanner.py
no puede ver.

Por que shortcut_scanner.py las pierde
-----------------------------------------
Windows representa una app de Store en el Menu Inicio con un .lnk
especial ("Application Reference") cuyo Targetpath queda VACIO para
WScript.Shell -- no apunta a un .exe real en disco, sino a un paquete
resuelto por el propio shell en tiempo de ejecucion. shortcut_scanner.py
descarta exactamente eso a proposito (`if not target or not
target.lower().endswith(".exe")`), asi que ninguna app de Store
aparecia nunca en la lista, sin importar cuantas veces se reescaneara.

Solucion: pedirselo al shell
-------------------------------
El cmdlet `Get-StartApps` de PowerShell es la misma fuente que usa el
Menu Inicio de Windows para poblarse: devuelve Name + AppID
(AppUserModelID) tanto de apps clasicas como empaquetadas, sin
distincion. Se identifican las empaquetadas por el formato de su AppID
('PackageFamilyName!AppId', con un '!' en el medio -- las clasicas
traen ahi la ruta completa a su .lnk).

Se cruza en la MISMA llamada con `Get-AppxPackage` (evita un segundo
proceso de PowerShell) para obtener InstallLocation, que es lo que
necesita core/icon_extractor.extract_uwp_icon para llegar al logo real
del paquete.

Se ejecuta todo en UN SOLO proceso de PowerShell: con decenas de apps
instaladas, un `powershell -Command` por app sumaria varios segundos
solo en overhead de arranque de proceso.

Nombres rotos ("ms-resource:...")
------------------------------------
Varias apps -- sobre todo de Microsoft -- no declaran su nombre como
texto plano en el manifest, sino como una referencia indirecta a un
recurso localizado (algo como 'ms-resource:AppStoreName' o ya
envuelto como '@{Paquete_hash?ms-resource://Paquete/resources/AppName}').
`Get-StartApps` normalmente ya viene con esto resuelto, pero para un
subconjunto de apps (mas frecuente en las de Microsoft, que son las que
mas usan este mecanismo) devuelve el string SIN resolver -- de ahi
"nombres incompletos o incorrectos" en la lista. El script de
PowerShell intenta resolverlo el mismo con `SHLoadIndirectString`
(la misma API que usa el propio Windows para esto); si falla, el lado
Python arma un nombre legible a partir del PackageFamilyName en vez de
mostrar el string tecnico sin resolver (ver _prettify_family_name).
"""

import hashlib
import json
import re
import subprocess

_TIMEOUT_S = 15

# subprocess.CREATE_NO_WINDOW solo existe en la version de subprocess de
# Windows (evita el parpadeo de una consola negra al lanzar powershell
# desde una app sin consola propia). Se lee con getattr para que el
# modulo siga siendo IMPORTABLE en cualquier entorno de desarrollo/CI
# que no sea Windows -- el resto del proyecto ya asume Windows en
# tiempo de EJECUCION (winreg, win32com, etc.), pero no hay motivo para
# que este modulo en particular no pueda al menos cargarse en otro
# lado.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# AppID (AppUserModelID) de componentes internos del propio shell de
# Windows que Get-StartApps expone pero que nunca son "un programa que
# el usuario abre a proposito" (hosts de notificaciones, dialogos
# internos, etc.). Mismo espiritu que _WINDIR / _LEGACY_WINDOWS_APPS en
# shortcut_scanner.py -- lista corta y explicita, pensada para ampliarse
# si aparece ruido nuevo, no un filtro agresivo que pueda esconder apps
# legitimas (Calculadora, Fotos, Store, etc. se dejan pasar).
_FAMILY_DENYLIST_PREFIXES = (
    "microsoft.windows.shellexperiencehost",
    "microsoft.windows.contentdeliverymanager",
    "microsoft.windows.cloudexperiencehost",
    "microsoft.windows.secondarytileexperience",
    "microsoft.windows.pinningconfirmationdialog",
    "microsoft.aad.brokerplugin",
    "microsoft.win32webviewhost",
    "microsoftwindows.client.cbs",
    "microsoft.microsoftedgedevtoolsclient",
)

# $ErrorActionPreference = 'SilentlyContinue' para que un paquete
# individual con metadata rara no tire abajo todo el script (queda con
# InstallLocation vacio en vez de abortar). -Compress evita indentado
# innecesario en la salida (da igual para json.loads, pero es menos
# texto para pasar por el pipe de stdout).
#
# Resolve-IndirectName intenta destapar un nombre 'ms-resource:...' (o
# ya envuelto en '@{...}') con SHLoadIndirectString -- la misma API de
# shlwapi.dll que usa el propio shell de Windows para mostrar el nombre
# real en el Menu Inicio. Si Add-Type no puede compilar el P/Invoke (por
# alguna politica de seguridad rara) o la resolucion falla por cualquier
# motivo, se devuelve $null y Python cae a su propio fallback (ver
# _prettify_family_name) en vez de romper el escaneo entero.
_PS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
# Nombres de apps con tildes, enies, o caracteres fuera de ASCII (comun
# en apps de Microsoft Store en espanol, o con nombre en otro idioma)
# llegaban rotos/con '?' -- subprocess.run(..., text=True) sin
# 'encoding=' explicito decodifica el stdout de powershell.exe con la
# codificacion ANSI/OEM del sistema (locale.getpreferredencoding()), que
# no coincide necesariamente con la que powershell.exe realmente usa al
# escribir en un pipe redirigido, y de cualquier forma ninguna de las
# dos puede representar todo lo que un nombre de app puede traer. Forzar
# ambos lados -- aca la salida de la consola a UTF-16 (la codificacion
# nativa de todo string de .NET/Windows, sin ninguna conversion de por
# medio) y en Python decodificar explicitamente como 'utf-16' (ver
# scan_uwp_apps) -- elimina la ambiguedad en vez de adivinarla.
[Console]::OutputEncoding = [System.Text.Encoding]::Unicode
try {
    Add-Type -MemberDefinition '[DllImport("shlwapi.dll", CharSet = CharSet.Unicode)] public static extern int SHLoadIndirectString(string pszSource, System.Text.StringBuilder pszOutBuf, int cchOutBuf, System.IntPtr ppvReserved);' -Namespace 'SpectrumLauncher' -Name 'Shlwapi' -ErrorAction Stop
} catch {}

function Resolve-IndirectName {
    param($RawName, $PackageFullName)
    if (-not $RawName) { return $null }
    if ($RawName -like '@{*') {
        $ref = $RawName
    } elseif ($RawName -like 'ms-resource:*') {
        if (-not $PackageFullName) { return $null }
        # Concatenado a mano: dentro de comillas dobles, PowerShell leeria
        # '$PackageFullName?' como el nombre de OTRA variable ('?' es un
        # caracter valido en nombres) y el paquete quedaria vacio.
        $ref = '@{' + $PackageFullName + '?' + $RawName + '}'
    } else {
        return $RawName
    }
    try {
        $sb = New-Object System.Text.StringBuilder 512
        $hr = [SpectrumLauncher.Shlwapi]::SHLoadIndirectString($ref, $sb, $sb.Capacity, [System.IntPtr]::Zero)
        if ($hr -eq 0 -and $sb.Length -gt 0) { return $sb.ToString() }
    } catch {}
    return $null
}

# Indice por PackageFamilyName: una busqueda directa por app en vez de
# recorrer todos los paquetes instalados por cada una.
$pkgs = @{}
foreach ($p in Get-AppxPackage) {
    if ($p.PackageFamilyName -and -not $pkgs.ContainsKey($p.PackageFamilyName)) {
        $pkgs[$p.PackageFamilyName] = $p
    }
}
Get-StartApps | ForEach-Object {
    $appId = $_.AppID
    if ($appId -notmatch '!') { return }
    $familyName = $appId.Split('!')[0]
    $pkg = $pkgs[$familyName]
    $resolved = Resolve-IndirectName -RawName $_.Name -PackageFullName $pkg.PackageFullName
    [PSCustomObject]@{
        Name            = $_.Name
        ResolvedName    = $resolved
        AppID           = $appId
        FamilyName      = $familyName
        InstallLocation = $pkg.InstallLocation
    }
} | ConvertTo-Json -Compress
"""


def _make_id(app_id: str) -> str:
    digest = hashlib.md5(app_id.lower().encode("utf-8")).hexdigest()[:10]
    return f"uwp_{digest}"


def _is_denied(family_name: str) -> bool:
    lower = (family_name or "").lower()
    return any(lower.startswith(prefix) for prefix in _FAMILY_DENYLIST_PREFIXES)


def _looks_unresolved(name) -> bool:
    """True si 'name' es un string de recurso SIN resolver en vez de un
    nombre real -- 'ms-resource:AppStoreName' o ya envuelto como
    '@{Paquete_hash?ms-resource://Paquete/resources/AppName}'. Pasa
    exactamente asi cuando ni Get-StartApps ni SHLoadIndirectString (ver
    _PS_SCRIPT) pudieron resolver el nombre localizado real del
    paquete."""
    if not name:
        return True
    return name.startswith("ms-resource") or name.startswith("@{")


def _prettify_family_name(family_name: str) -> str:
    """Ultimo recurso si ni Get-StartApps ni SHLoadIndirectString dieron
    un nombre usable: arma algo legible a partir del PackageFamilyName
    (que siempre existe, es el identificador estable del paquete). No es
    el nombre 'oficial' -- pero es mejor que mostrar un string tecnico
    sin resolver en la lista de apps."""
    name_part = (family_name or "").split("_")[0]  # saca el sufijo hash del publisher
    for prefix in ("Microsoft.", "Windows."):
        if name_part.startswith(prefix):
            name_part = name_part[len(prefix):]
            break
    name_part = name_part.replace(".", " ").replace("_", " ")
    # separa PascalCase/CamelCase en palabras: "WindowsCalculator" -> "Windows Calculator"
    name_part = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name_part)
    name_part = re.sub(r"\s+", " ", name_part).strip()
    return name_part or family_name or "App de Microsoft Store"


def scan_uwp_apps():
    """Lista de entradas compatibles con launchers.json, mas una clave
    temporal 'install_location' que LauncherManager.refresh() usa para
    resolver el icono y descarta antes de guardar.

    Devuelve None si la deteccion FALLO (PowerShell no esta, tardo
    demasiado o devolvio algo ilegible) y [] si funciono pero no hay
    apps. La diferencia importa: ante un fallo, refresh() conserva las
    apps de Microsoft Store que ya tenia en vez de borrarlas."""
    try:
        # Bytes crudos (sin text=True): el script fuerza la salida a
        # UTF-16 y aca se decodifica igual, sin depender de la
        # codificacion ANSI/OEM del sistema.
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
            capture_output=True,
            timeout=_TIMEOUT_S,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return None

    if proc.returncode != 0:
        return None
    if not proc.stdout:
        return []

    try:
        # "utf-16" (no "utf-16-le"): si llega un BOM se usa, y si no, cae
        # a little-endian, que es lo que escribe Windows.
        stdout_text = proc.stdout.decode("utf-16", errors="replace")
    except Exception:
        return None

    if not stdout_text.strip():
        return []

    try:
        raw = json.loads(stdout_text)
    except ValueError:
        return None

    # ConvertTo-Json no envuelve en lista si Get-StartApps solo hubiera
    # devuelto UN resultado empaquetado -- lo normalizamos a lista para
    # no tener que distinguir los dos casos mas abajo.
    if isinstance(raw, dict):
        raw = [raw]
    elif not isinstance(raw, list):
        return None

    results = []
    seen_ids = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        app_id = item.get("AppID")
        family_name = item.get("FamilyName") or ""
        if not app_id:
            continue
        # El script de PowerShell ya filtra por esto (`-notmatch '!'`),
        # pero se vuelve a chequear aca del lado de Python: si el dia de
        # manana cambia la version de PowerShell/el formato de salida y
        # ese filtro deja de aplicarse como se espera, no queremos que
        # una app clasica (cuyo "AppID" en ese caso es la ruta a su
        # .lnk, no un AppUserModelID) termine con un target roto tipo
        # "shell:AppsFolder\C:\...\Algo.lnk".
        if "!" not in app_id:
            continue
        if _is_denied(family_name):
            continue

        # Preferencia: nombre resuelto por SHLoadIndirectString -> nombre
        # crudo de Get-StartApps (si ya viene bien) -> nombre armado a
        # partir del PackageFamilyName. Nunca se deja pasar un string de
        # recurso sin resolver a la UI.
        resolved_name = item.get("ResolvedName")
        raw_name = item.get("Name")
        if resolved_name and not _looks_unresolved(resolved_name):
            name = resolved_name
        elif raw_name and not _looks_unresolved(raw_name):
            name = raw_name
        else:
            name = _prettify_family_name(family_name)

        entry_id = _make_id(app_id)
        if entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)

        results.append({
            "id": entry_id,
            "name": name,
            "type": "uwp",
            # "shell:AppsFolder\<AppUserModelID>" es la forma documentada
            # de pedirle a Windows que lance una app empaquetada -- es
            # exactamente lo que hace Windows por detras al abrir su
            # icono desde el Menu Inicio. LauncherManager.launch() ya
            # funciona sin cambios porque usa os.startfile(), que
            # internamente llama a ShellExecute (entiende rutas "shell:").
            "target": f"shell:AppsFolder\\{app_id}",
            "icon": "auto",
            "install_location": item.get("InstallLocation") or "",
            "source": "auto",
            "close_after_launch": True,
        })

    return results
