#!/usr/bin/env python
# This script is used to package python's portable version.
# It's only targeted at Windows platform.

import os
import re
import io
import sys
import stat
import json
import zlib
import shutil
import hashlib
import pycurl
import base64
from zipfile import ZipFile
from configparser import ConfigParser
try:
    import packaging
    import packaging.specifiers
    from packaging.version import parse as parse_version
except ImportError:
    from pkg_resources import packaging, parse_version

try:
    from gzip import _GzipReader, BadGzipFile
except ImportError:
    BadGzipFile = OSError

skip_pkg = 0
only_pkg = 0
allow_prerelease = None


sitecustomize = b'''\
import os
import sys
import glob
from _frozen_importlib_external import \
        EXTENSION_SUFFIXES, SourceFileLoader, \
        ExtensionFileLoader, spec_from_file_location

py_dir = os.path.abspath(os.path.join(
    __file__,
    * ['..'] * (isinstance(__loader__, SourceFileLoader) and 1 or 2) ))

def find_loader(self, fullname, path=None):
    loader, portion = find_loader.orig(self, fullname)
    if loader is None:
        path = zip_find_extension(self, fullname)
        if path:
            return ExtensionFileLoader(fullname, path), []
    return loader, portion

def find_spec(self, fullname, target=None):
    spec = find_spec.orig(self, fullname)
    if getattr(spec, 'loader', None) is None:
        path = zip_find_extension(self, fullname)
        if path:
            return spec_from_file_location(fullname, path)
    return spec

def zip_find_extension(self, fullname):
    path = self.prefix + fullname.rpartition('.')[2]
    for suffix in EXTENSION_SUFFIXES:
        dll_path = path + suffix
        if dll_path in self._files:
            path = os.path.join(eggs_cache,
                                os.path.basename(self.archive) + '-tmp',
                                dll_path)
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'wb') as f:
                    f.write(self.get_data(dll_path))
            return path

def patch_zipimporter():
    from zipimport import zipimporter
    if hasattr(zipimporter, 'find_spec'):
        find_spec.orig = zipimporter.find_spec
        zipimporter.find_spec = find_spec
    else:
        find_loader.orig = zipimporter.find_loader
        zipimporter.find_loader = find_loader

def set_prefix():
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE'):
        os.environ.pop(name, None)
    sys.prefix = py_dir
    sys.base_prefix = py_dir
    sys.exec_prefix = py_dir
    sys.base_exec_prefix = py_dir
    import site
    site.PREFIXES[:] = [py_dir]
    site.USER_SITE = None
    site.USER_BASE = None

def set_path():
    global eggs_cache
    sys.executable = sys._base_executable = os.path.join(py_dir, 'python.exe')
    if 'VIRTUAL_ENV' in os.environ:
        home = os.environ['PYTHONHOME']
        prompt = os.environ.get('VIRTUAL_PROMPT')
        dlls = os.path.join(home, 'DLLs')
        for i, path in enumerate(sys.path):
            if path == dlls:
                sys.path[i] = os.path.join(py_dir, 'DLLs')
            elif path.endswith('site-packages'):
                if os.path.exists(path):
                    sys.path[i+1:i+1] = glob.glob(os.path.join(path, '*.egg'))
                    break
        eggs_cache = os.path.join(home, 'Eggs-Cache')
        if prompt:
            sys.ps1 = prompt + ' >>> '
            sys.ps2 = ' ' * len(prompt) + ' ... '
    else:
        if not (py_dir == sys.prefix == sys.base_prefix ==
                          sys.exec_prefix == sys.base_exec_prefix):
            set_prefix()
        sp_dir = os.path.join(py_dir, 'site-packages')
        sys.path[:] = [os.path.join(py_dir,
                       'python%d%d.zip' % sys.version_info[:2])]
        sys.path.append(os.path.join(py_dir, 'DLLs'))
        if os.path.exists(sp_dir):
            sys.path.append(sp_dir)
            sys.path.extend(glob.glob(os.path.join(sp_dir, '*.egg')))
        sys.path.append(py_dir)
        eggs_cache = os.path.join(py_dir, 'Eggs-Cache')

def main():
    set_path()
    os.environ['EGGS_CACHE'] = eggs_cache
    try:
        import zipextimporter
    except ImportError:
        patch_zipimporter()
    else:
        zipextimporter.install()
        modules = os.path.join(py_dir, 'memimport_exclude_modules')
        if os.path.isfile(modules):
            # debug
            modules = open(modules, 'r').read().split()
        elif sys.getwindowsversion() < (10,):
            # NT 6
            modules = ['greenlet._greenlet']
            try:
                assert int(__import__('cryptography').__version__.split('.')[0]) >= 41
            except:
                pass
            else:
                modules += ['cryptography.hazmat.bindings._rust']
        elif __import__('struct').calcsize('P') == 8:
            # NT 10 x64
            modules = ['cryptography.hazmat.bindings._rust']
        zipextimporter.set_exclude_modules(modules)

main()
'''

simplewinvenv = b'''\
"""
A simple virtual environment script for Python.
Additional files must be copied manually, if need.
It's only targeted at Windows platform.
"""

import os
import sys

help = """\
Creates a simple virtual environment for Python

Use:  python -m svenv venvdir [prompt]

  venvdir       A directory to create the environment in.
  prompt        Provides an alternative prompt prefix for this environment.
                If not set, will use the directory name.

"""

activate_bat = """\\
@echo off
set VIRTUAL_ENV=%~dp0
set VIRTUAL_PROMPT={prompt}
set PYTHONNOUSERSITE=
set PYTHONHOME=%VIRTUAL_ENV%
set _PYTHON_PROJECT_BASE=%VIRTUAL_ENV%
set PATH=%VIRTUAL_ENV%Scripts;{exe_dir};%VIRTUAL_ENV%;%PATH%
if not defined PROMPT set PROMPT=$P$G
set PROMPT=({prompt}) %PROMPT%
echo on
"""

launcher_bat = """\\
@if not defined VIRTUAL_ENV call "%~dp0activate.bat"
@"{exe}" %*
"""

console_bat = """\\
@if not defined VIRTUAL_ENV (
    call "%~dp0activate.bat"
    cmd
)
"""

def create(env_dir, prompt):
    lib_dir = os.path.join(env_dir, 'Lib')
    sp_dir = os.path.join(env_dir, lib_dir, 'site-packages')
    exe_dir = os.path.dirname(sys.executable)
    os.makedirs(sp_dir, exist_ok=True)
    with open(os.path.join(env_dir, 'activate.bat'), 'w') as f:
        f.write(activate_bat.format(prompt=prompt, exe_dir=exe_dir))
    with open(os.path.join(env_dir, 'python.bat'), 'w') as f:
        f.write(launcher_bat.format(exe=sys.executable))
    with open(os.path.join(env_dir, 'console.bat'), 'w') as f:
        f.write(console_bat)
    print('New virtual environment created at %r, prompt is %r.'
          % (env_dir, prompt))

def main():
    try:
        env_dir = sys.argv[1]
    except IndexError:
        print(help)
        return
    if not os.path.isabs(env_dir) or os.path.isfile(env_dir):
        raise ValueError("The environment path must be absolute, "
                         "and can't be a exists file.")
    try:
        prompt = sys.argv[2]
    except IndexError:
        prompt = os.path.basename(env_dir.rstrip(os.path.sep))
    create(env_dir, prompt)

if __name__ == '__main__':
    rc = 1
    try:
        main()
        rc = 0
    except Exception as e:
        print('Error: %s' % e, file=sys.stderr)
    sys.exit(rc)
'''


def download_apiset_corepath(filename, arch, sum):
    zipfile = download('https://github.com/nalexandru/api-ms-win-core-path-HACK'
                       '/releases/download'
                       '/0.3.1/api-ms-win-core-path-blender-0.3.1.zip',
                       sum=sum)
    newfilename = os.path.splitext(filename)[0]
    filepath = f'api-ms-win-core-path-blender/{arch}/{newfilename}'
    os.system(f'{_7z} e {zipfile} {filepath} {to_null}')
    os.remove(zipfile)
    os.rename(newfilename, filename)

dlls = {
    'win32': (
        (download_apiset_corepath, 'api-ms-win-core-path-l1-1-0.dll.w7',
        'x86', 'md5|a40e20f59a12b71ca5f2997d9111519c'),
    ),
    'win_amd64': (
        (download_apiset_corepath, 'api-ms-win-core-path-l1-1-0.dll.w7',
        'x64', 'md5|a40e20f59a12b71ca5f2997d9111519c'),
    )
}

useless_exes = '''\
pythonw.exe
vcruntime140.dll
vcruntime140_1.dll
_msi.pyd
_distutils_findvs.pyd
winsound.pyd
'''.split()

_7z = '7z'
to_null = os.name == 'nt' and '1>nul' or '1>/dev/null'
ca1 = 'cert/CA.crt'
ca2 = 'cert/cacerts/mozilla.pem'
if os.path.exists(ca1):
    ca = os.path.realpath('ca.pem')
    if not os.path.exists(ca):
        with open(ca, 'wb') as f:
            with open(ca1, 'rb') as f1:
                f.write(f1.read())
            with open(ca2, 'rb') as f2:
                f.write(f2.read())
else:
    ca = os.path.realpath(ca2)

STRING = b'STRING'
BYTES = b'BYTES'
JSON = b'JSON'
IO = b'IO'
ARB = re.compile(b'Accept-Ranges:\s?bytes', re.I).search
CEG = re.compile(b'Content-Encoding:\s?gzip', re.I).search

def _download(url, f):
    f.reset_headers()
    start = f.tell()
    c = pycurl.Curl()
    c.setopt(c.CAINFO, ca)
    c.setopt(c.SSL_VERIFYHOST, 2)
    c.setopt(c.BUFFERSIZE, 32768)
    c.setopt(c.TIMEOUT, 60)
    c.setopt(c.FOLLOWLOCATION, 1)
    c.setopt(c.MAXREDIRS, 3)
    c.setopt(c.URL, url)
    c.setopt(c.WRITEFUNCTION, f.write_cb)
    c.setopt(c.HEADERFUNCTION, f.header_cb)
    if start:
        c.setopt(c.RANGE, f'{start:d}-')
    if f.filepath in (STRING, BYTES, JSON):
        # With ACCEPT_ENCODING then decompress received contents automatically.
        # With HTTPHEADER then will not do that, we need this for request RANGE.
        c.setopt(c.HTTPHEADER, ['Accept-Encoding: gzip'])
    try:
        c.perform()
        ok = c.getinfo(c.RESPONSE_CODE) in (200, 206)
    finally:
        c.close()
    return ok

class file:
    def __init__(self, filepath, sum='|'):
        self.f = None
        self.filepath = filepath
        self.algorithm, self.sum = sum.split('|')
        self.reset_headers()
        self.new_file()

    def new_file(self):
        self.close()
        if self.filepath in (STRING, BYTES, JSON, IO):
            self.f = io.BytesIO()
        else:
            self.f = open(self.filepath, 'wb')
        if self.algorithm:
            self.m = hashlib.new(self.algorithm)
        else:
            self.m = None
        self._size = 0
        self.fgzip = None
        self.fungzip = None

    def tell(self):
        return self._size

    def getio(self):
        return self.fungzip or self.f

    def getvalue(self):
        return self.getio().getvalue()

    def write_cb(self, data):
        if self.accept_ranges is None:
            self.accept_ranges = bool(ARB(self.headers))
            if self.f.tell() and not self.accept_ranges:
                self.new_file()
            if self.fgzip is None and bool(CEG(self.headers)):
                self.fgzip = _GzipReader(self.f)
                self.fungzip = io.BytesIO()
        if self.fgzip:
            offset = self.f.tell()
            self.f.seek(0, io.SEEK_END)
        self._size += self.f.write(data)
        chunks = [data]
        if self.fgzip:
            self.f.seek(offset)
            chunks.clear()
            while data:
                offset = self.f.tell()
                try:
                    data = self.fgzip.read(sys.maxsize)
                except (EOFError, BadGzipFile):
                    if offset == 0:
                        self.fgzip._rewind()
                    elif self.fgzip._decompressor.eof:
                        self.f.seek(offset)
                    break
                chunks.append(data)
            for chunk in chunks:
                self.fungzip.write(chunk)
        if self.m:
            for chunk in chunks:
                self.m.update(chunk)

    def header_cb(self, data):
        self.headers += data

    def reset_headers(self):
        self.headers = b''
        self.accept_ranges = None

    def close(self):
        if self.filepath is IO:
            return
        try:
            self.f.close()
        except AttributeError:
            pass

    def check_sum(self):
        if self.m:
            return self.m.hexdigest() == self.sum
        return True

def download(url, filepath=None, sum='|'):
    if not filepath:
        name_parts = url.split('/')[2:]
        filepath = name_parts.pop()
        while not filepath and name_parts:
            filepath = name_parts.pop()
    print(f'start download {url!r} to {filepath!r}.')

    f = file(filepath, sum)
    ok = False
    retry = 0
    max_retry = 10
    while not ok and retry <= max_retry:
        try:
            ok = _download(url, f)
        except Exception as e:
            print(f'download {url!r} error: {e}.', file=sys.stderr)
            err = e
        else:
            if not ok and retry == max_retry:
                f.new_file()
        retry += 1

    if ok:
        ok = f.check_sum()
        if ok:
            if filepath is STRING:
                res = f.getvalue().decode()
            elif filepath is BYTES:
                res = f.getvalue()
            elif filepath is JSON:
                res = json.loads(f.getvalue().decode())
            elif filepath is IO:
                res = f.getio()
            else:
                res = filepath
        else:
            err = 'hash check failed'
    else:
        err = 'response status is wrong'
    f.close()
    if ok:
        print(f'download {url!r} to {filepath!r} over.')
        return res
    else:
        print(f'download {url!r} fail: {err}.', file=sys.stderr)
        sys.exit(1)

def download_as_extracter(url, sum='|'):
    file = download(url, IO, sum)

    def extract(ext, path=None):
        if ext and ext[0] != '.':
            ext = '.' + ext
        with ZipFile(file) as zf:
            for filename in zf.namelist():
                if filename.endswith(ext):
                    zf.extract(filename, path)

    return extract


## Python embed
def pack_pyembed():
    if not os.path.exists('python/python.exe'):
        filepath = download(py_url, sum=py_sum)
        os.system(f'{_7z} e {filepath} -opython {to_null}')
        os.remove(filepath)
    os.chdir('python')
    for filename in useless_exes:
        try:
            os.remove(filename)
        except:
            pass
    is_dll = re.compile('^(?!python\d).+\.(dll|pyd)$').match
    for dir in ('DLLs', 'pythonzip'):
        if not os.path.exists(dir):
            os.mkdir(dir)
    url, _, sum = fetch_info('memimport', memimport_ver)[0]
    memimport_zip = download_as_extracter(url, sum)
    memimport_zip('pyd', 'DLLs')
    pythonzip = None
    for filename in os.listdir():
        if filename.endswith(('.txt', '.cat', '.cfg', '._pth')):
            os.remove(filename)
        elif is_dll(filename):
            os.rename(filename, os.path.join('pythonzip', filename))
        elif filename.endswith('.zip'):
            pythonzip = filename
            os.system(f'{_7z} x {filename} -opythonzip {to_null}')
            os.remove(filename)
            memimport_zip('py', 'pythonzip')
            with open('pythonzip/sitecustomize.py', 'wb') as f:
                f.write(sitecustomize)
            with open('pythonzip/svenv.py', 'wb') as f:
                f.write(simplewinvenv)
    if pythonzip:
        os.system(f'{_7z} a -mx=9 -mfb=258 -mtc=off {to_null} {pythonzip} ./pythonzip/*')
        shutil.rmtree('pythonzip', True)
    if int(py_vers[1]) >= 9:
        install_dlls = ['''\
for /f "tokens=2 delims=[" %%v in ('ver') do set version=%%v
for /f "tokens=2" %%v in ('echo %version%') do set version=%%v
for /f "delims=]" %%v in ('echo %version%') do set version=%%v
if %version% lss 6.2 ( goto :install )''']
        for _, filename, *args in dlls[py_arch]:
            install_dlls.append(f'if exist {filename} del {filename}')
        install_dlls.append('''
:del_self
  del %0
  goto :EOF

:install''')
        for generator, filename, *args in dlls[py_arch]:
            if not os.path.exists(filename):
                generator(filename, *args)
            newfilename = os.path.splitext(filename)[0]
            install_dlls.append(f'  if exist {newfilename} del {newfilename}')
            install_dlls.append(f'  rename {filename} {newfilename}')
        install_dlls.append('  goto :del_self')
        with open('install_dll.bat', 'w', newline='\r\n') as f:
            f.write('\n'.join(install_dlls))


## Python packages
pypi_api = 'https://pypi.org/pypi/{}/json'.format
pypi_ver_api = 'https://pypi.org/pypi/{}/{}/json'.format

class SpecifierSet(packaging.specifiers.SpecifierSet):
    _allow_yanked = None

    def __init__(self, specifiers, prereleases=None):
        parsed = set()
        for specifier in specifiers.split(','):
            specifier = specifier.strip()
            if not specifier:
                continue
            if specifier[-1] == '!':
                specifier = specifier[:-1]
                pre = True
            else:
                pre = None
            parsed.add(packaging.specifiers.Specifier(specifier, pre))
        self._specs = frozenset(parsed)
        self._prereleases = prereleases

    @property
    def allow_yanked(self):
        if self._allow_yanked is None:
            self._allow_yanked = any(spec.operator[:2] == '=='
                                     for spec in self._specs)
        return self._allow_yanked

def fetch_info(project, specifiers=''):
    data = download(pypi_api(project), JSON)
    if specifiers and specifiers[0] not in '<>!~=':
        project_sub, _, specifiers = specifiers.partition(' ')
    else:
        project_sub = None
    specifiers = SpecifierSet(specifiers, allow_prerelease)
    releases = sorted(((parse_version(key), key) for key in data['releases']),
                      key=lambda r: r[0], reverse=True)
    dists = None
    for release, key in releases:
        if not specifiers or release in specifiers:
            dists = sorted(data['releases'][key],
                           key=lambda d: d['python_version'], reverse=True)
            if not dists[0]['yanked'] or specifiers.allow_yanked:
                break
            dists = None
    if not dists:
        print(f'{project} mismatch specifiers: {specifiers}', file=sys.stderr)
        sys.exit(1)
    dist_type = None
    for dist in dists:
        if dist['packagetype'] in ('bdist_wheel', 'bdist_egg') and (
                is_supported_tags_1(dist['filename']) or
                is_supported_tags_2(dist['filename'])):
            dist_type = dist['packagetype']
            break
    if not dist_type:
        for dist in dists:
            if dist['python_version'] == 'source':
                dist_type = dist['packagetype']
                break
    url = dist['url']
    filename = dist['filename']
    sum = '|'.join(('sha256', dist['digests']['sha256']))
    return (url, filename, sum), project_sub

def extract(project_info, project_sub):
    filename = project_info[1]
    if project_sub:
        filename = filename.replace(project, project_sub)
    while True:
        filename = filename.rpartition('.')[0]
        if not filename.endswith('.tar'):
            filename += '.egg'
            if os.path.exists(filename):
                return
            else:
                break
    filepath = download(*project_info)
    if filepath.endswith(('.tar.gz', '.tar.xz', '.tar.bz2')):
        os.system(f'{_7z} e {filepath} {to_null}')
        os.remove(filepath)
        filepath = filepath.rpartition('.')[0]
    if filepath.endswith(('.whl', '.egg', '.tar', '.zip')):
        os.system(f'{_7z} x -y {filepath} {to_null}')
        if os.path.exists('@PaxHeader'):
            os.chmod('@PaxHeader', stat.S_IWRITE)
            os.remove('@PaxHeader')
        os.remove(filepath)
    if filepath.endswith(('.tar', '.zip')):
        # This is source code, may require a complicated installation process.
        # But in most cases, just pack it is okay.
        name = filepath[:-4]
        updir = '..'
        if os.path.exists(os.path.join(name, 'src')):
            name = os.path.join(name, 'src')
            updir = os.path.join('..', '..')
        for dirpath, dirnames, filenames in os.walk(name):
            for dirname in dirnames:
                old = os.path.join(dirpath, dirname)
                new = os.path.join(dirpath, updir, dirname)
                os.rename(old, new)
            for filename in filenames:
                if filename.startswith(('setup.', 'fuzz.')) or \
                        not filename.endswith('.py'):
                    continue
                old = os.path.join(dirpath, filename)
                new = os.path.join(dirpath, updir, filename)
                os.rename(old, new)
        shutil.rmtree(filepath[:-4])
    name = filepath.rpartition('.')[0]
    if project_sub:
        name = name.replace(project, project_sub)
        for dirpath, dirnames, filenames in os.walk('.'):
            for dirname in dirnames:
                if dirname != project_sub:
                    filepath = os.path.join(dirpath, dirname)
                    shutil.rmtree(filepath, True)
            for filename in filenames:
                if not filename.endswith('.egg'):
                    filepath = os.path.join(dirpath, filename)
                    os.remove(filepath)
            break
    return name

def package(name):
    if not name:
        return
    abi3 = 'abi3' in name
    if 'zope.' in name:
        import glob
        nspkgpth = glob.glob('zope.*-nspkg.pth')
        if nspkgpth:
            os.remove(nspkgpth[0])
            with open('zope/__init__.py', 'wb') as f:
                f.write(b'__import__("pkg_resources").declare_namespace(__name__)\n')
    for dirpath, dirnames, filenames in os.walk('.'):
        for dirname in dirnames:
            if dirname in ('test', 'tests', 'testing'):
                filepath = os.path.join(dirpath, dirname)
                shutil.rmtree(filepath, True)
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if filename == 'testing.py' and ('pyparsing' in name or
                                             'pkg_resources' in name):
                with open(filepath, 'wb') as f:
                    f.write(b'pyparsing_test = None\n')
            elif filename.endswith(('.pyx', '.pyi',  '.pxd', 'ffi_build.py', '.html',
                                '.c', '.h', '.cpp', '.hpp', '.asm', '.obj')) or \
                    filename.startswith(('test.', 'tests.', 'testing.')) or \
                    (filename != '__init__.py' and os.path.getsize(filepath) == 0):
                os.remove(filepath)
            elif filename.endswith('.pyd') and not abi3 and dll_tag not in filename:
                newname = f'{filename[:-3]}{dll_tag}.pyd'
                os.rename(os.path.join(dirpath, filename),
                          os.path.join(dirpath, newname))
                print(f'Warning: filename {filename!r} '
                      f'does not match the dll_tag {dll_tag!r}, '
                      f'rename it as {newname!r}.')
    os.system(f'{_7z} a -tzip -x!*.egg -mx=9 -mfb=258 -mtc=off {to_null} {name}.egg *')
    for dirpath, dirnames, filenames in os.walk('.'):
        for dirname in dirnames:
            filepath = os.path.join(dirpath, dirname)
            shutil.rmtree(filepath, True)
        for filename in filenames:
            if not filename.endswith('.egg'):
                filepath = os.path.join(dirpath, filename)
                os.remove(filepath)
        break


if __name__ == '__main__':
    # read settings
    ConfigParser.optionxform = lambda s, opt: opt
    config = ConfigParser()
    config.read('pack_portable.ini')
    if len(sys.argv) < 2:
        print('missing version parameter!', file=sys.stderr)
        sys.exit(1)
    py_ver = sys.argv[1]
    if py_ver not in config.sections():
        print('version parameter mismatch!', file=sys.stderr)
        sys.exit(1)
    extras = sys.argv[2:]

    py_url = config.get(py_ver, 'url')
    py_sum = config.get(py_ver, 'sum')
    py_ver, py_arch = py_ver.split('-')
    py_vers = py_ver.split('.')
    py_ver = ''.join(py_vers[:2])
    dll_tag = f'cp{py_ver}-{py_arch}'
    memimport_ver = config.get('memimport', 'version')

    sub_vers = (len(py_vers[1]) == 1 and
            f'[{{}}-{py_vers[1]}]' or
            f'[{{}}-9]|[1-{py_vers[1][0]}][0-{py_vers[1][1]}]').format
    flag = int(py_vers[1]) < 8 and 'm?' or ''
    is_supported_tags_1 = re.compile(
            f'(cp|py)3({sub_vers(0)})?-(cp{py_ver}{flag}|none)-({py_arch}|any)'
            ).search
    is_supported_tags_2 = re.compile(
            f'cp3({sub_vers(2)})-abi3-{py_arch}'
            ).search

    if only_pkg:
        os.chdir('python')
    else:
        pack_pyembed()

    if skip_pkg: sys.exit()

    if not os.path.exists('site-packages'):
        os.mkdir('site-packages')
    os.chdir('site-packages')

    for project, specifiers in config.items('site-packages'):
        package((extract(*fetch_info(project, specifiers))))

    for project in extras:
        specifiers = config.get('extras-site-packages', project, fallback='')
        package(extract(*fetch_info(project, specifiers)))
