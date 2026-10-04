"""Long operations run in isolated worker processes."""
import json
import os
from pathlib import Path
import sys
import codec

def main():
    job = Path(sys.argv[1])
    request = json.loads((job / 'request.json').read_text(encoding='utf-8'))
    try:
        if request['action'] == 'open':
            result = codec.prepare(request['source'], job / 'save',request.get('game'))
        elif request['action'] == 'export':
            result = codec.export(request['folder'], request['changes'], request['target'])
        elif request['action'] == 'steam':
            import steam_achievements
            result = steam_achievements.run(request['operation'], request.get('game'),
                request.get('achievement'), request.get('confirmed', False))
        else:
            raise ValueError('Unknown job')
        status = {'state': 'done', 'result': result}
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    temp = job / 'status.tmp'
    temp.write_text(json.dumps(status), encoding='utf-8')
    os.replace(temp, job / 'status.json')

if __name__ == '__main__':
    main()
