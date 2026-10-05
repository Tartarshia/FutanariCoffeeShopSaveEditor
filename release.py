"""Audit tracked source and create a reproducible, source-only release ZIP."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
ROOT_FILES = {'AGENTS.md','.gitignore','.gitattributes','LICENSE','THIRD_PARTY_NOTICES.md','README.md',
    'RESEARCH.md','SAVE_FORMAT.md','analysis.py','codec.py','game_data.py','model.py',
    'schema.py','tasks.py','unity_assets.py','web_server.py','steam_achievements.py',
    'release.py','appearance.py','preview.py','unity_preview.py','wardrobe.py','启动存档编辑器.cmd'}
EXTENSIONS = {'web':{'.js','.html','.css'},'tests':{'.py'},'.github':{'.yml'}}
PATTERNS = [r'(?i)[a-z]:[\\/]Users[\\/]', r'/ho' + r'me/[^/\s]+/',
    r'(?i)gh[pousr]_[A-Za-z0-9]{20,}', r'github_pat_[A-Za-z0-9_]{20,}',
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    r'7656119\d{10}', r'(?i)(?:api_key|password|secret)\s*[:=]\s*[\x22\x27][A-Za-z0-9/+_-]{24,}']

def tracked_files():
    data=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT)
    return sorted(x.decode('utf-8') for x in data.split(b'\0') if x)

def tracked_bytes(name):
    return subprocess.check_output(['git','show',':'+name],cwd=ROOT)

def audit(files):
    if not {'LICENSE','THIRD_PARTY_NOTICES.md','RESEARCH.md'} <= set(files):
        raise ValueError('Required public notices missing')
    for name in files:
        p=PurePosixPath(name)
        allowed=name in ROOT_FILES or (len(p.parts)>=2 and p.parts[0] in EXTENSIONS
            and p.suffix in EXTENSIONS[p.parts[0]]
            and (p.parts[0]!='.github' or name=='.github/workflows/tests.yml'))
        if not allowed or '..' in p.parts:
            raise ValueError('Unexpected public file: '+name)
        path=ROOT/name
        if path.is_symlink() or path.stat().st_size>1048576:
            raise ValueError('Unexpected link or large file: '+name)
        source=path.read_bytes().replace(b'\r\n',b'\n')
        staged=tracked_bytes(name)
        if source!=staged.replace(b'\r\n',b'\n'):
            raise ValueError('Unstaged public changes: '+name)
        content=staged.decode('utf-8')
        for pattern in PATTERNS:
            if re.search(pattern,content):
                raise ValueError('Privacy pattern found in '+name)
    return files

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    files=audit(tracked_files())
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with open(args.output,'xb') as output:
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for name in files:
                    info=zipfile.ZipInfo('FutanariCoffeeShopSaveEditor/'+name,(2026,10,4,0,0,0))
                    info.compress_type=zipfile.ZIP_DEFLATED
                    info.external_attr=0o100644<<16
                    archive.writestr(info,tracked_bytes(name))
        with zipfile.ZipFile(args.output) as archive:
            if archive.testzip() is not None or len(archive.namelist())!=len(files):
                raise ValueError('Archive validation failed')
    print('PUBLIC_SOURCE_AUDIT_PASS',len(files),'files')

if __name__=='__main__':
    main()
