"""Read-only download/content checks against the isolated browser acceptance service."""
import io
import json
from pathlib import Path
import httpx
from openpyxl import load_workbook

root = Path(__file__).resolve().parents[2]
manifest = json.loads((root / 'outputs/browser-acceptance-session.json').read_text('utf-8'))
assert manifest['database'] == 'SQLite' and manifest['backend_port'] == 8001
out = root / 'outputs/web-export-verification'
out.mkdir(exist_ok=True)
results = []
with httpx.Client(base_url='http://127.0.0.1:8001/api', timeout=30) as client:
    assert 'SQLite' in client.get('/health').json()['database']
    login = client.post('/auth/login', json={'username': 'farmer', 'password': Path(manifest['credential_file']).read_text('utf-8')})
    login.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + login.json()['token']
    for label, endpoint, extension in [
        ('lands', '/reports/lands/xlsx', 'xlsx'),
        ('lands', '/reports/lands/pdf', 'pdf'),
        ('lands', '/records/lands/export/csv', 'csv'),
        ('finance', '/finance/export/xlsx?year=2026&include_demo=false', 'xlsx'),
        ('finance', '/finance/export/pdf?year=2026&include_demo=false', 'pdf'),
    ]:
        response = client.get(endpoint)
        response.raise_for_status()
        content = response.content
        path = out / f'{label}.{extension}'
        path.write_bytes(content)
        if extension == 'xlsx':
            book = load_workbook(io.BytesIO(content), read_only=True)
            assert book.sheetnames and any(list(book.active.values))
            book.close()
        elif extension == 'pdf':
            assert content.startswith(b'%PDF-') and b'%%EOF' in content[-100:]
        else:
            assert content.decode('utf-8-sig').strip()
        results.append({'check': path.name, 'passed': True, 'bytes': len(content), 'method': 'HTTP content verification, not browser download'})
    for file in client.get('/files').json():
        if file['name'] == 'browser-acceptance-attachment.txt':
            response = client.get('/files/' + str(file['id']))
            response.raise_for_status()
            assert response.content == (root / 'outputs/browser-acceptance-attachment.txt').read_bytes()
            results.append({'check': 'attachment round trip', 'passed': True, 'method': 'HTTP byte comparison after browser upload'})
            break
    else:
        raise AssertionError('Browser upload missing')
(out / 'checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'{len(results)} download/content checks passed; browser file saving remains separate.')
