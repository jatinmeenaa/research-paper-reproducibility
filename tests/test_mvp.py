import io
import json
import re
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

import pymupdf
from werkzeug.serving import make_server

from app import create_app
from src.analysis import latest_job, start_analysis
from src.database.db import get_paper, get_resources, init_db, save_paper
from src.scoring import calculate_score


class MVPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.settings = {
            'TESTING': True, 'SECRET_KEY': 'isolated-test-key',
            'DATABASE': self.root / 'test.db',
            'UPLOAD_FOLDER': self.root / 'uploads',
            'RECOVER_INTERRUPTED_JOBS': False,
        }
        self.app = create_app(self.settings)
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def token(self):
        self.client.get('/')
        with self.client.session_transaction() as session:
            return session['csrf_token']

    def pdf(self):
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((50, 50), 'Implementation: https://github.com/example/project')
            page.insert_text((50, 80), 'Research methods and experimental details. ' * 4)
            page.insert_link({'kind': pymupdf.LINK_URI,
                              'from': pymupdf.Rect(50, 100, 250, 120),
                              'uri': 'https://zenodo.org/records/123'})
            return document.tobytes()

    def upload(self, data=None):
        return self.client.post('/upload', data={
            'csrf_token': self.token(),
            'pdf': (io.BytesIO(data if data is not None else self.pdf()), 'study.pdf'),
            'title': 'Example paper', 'year': '2024', 'area': 'Computer science',
        })

    @staticmethod
    def available(resource):
        return {**resource, 'status': 'accessible', 'http_status': 200,
                'final_url': resource['url'], 'note': 'Test response',
                'checked_at': '2026-01-01T00:00:00+00:00'}

    def wait(self, paper_id):
        for _ in range(200):
            with self.app.app_context():
                job = latest_job(paper_id)
            if job and job['status'] not in ('queued', 'running'):
                self.assertEqual(job['status'], 'completed', job)
                return
            time.sleep(0.025)
        self.fail('Analysis did not finish')

    def test_pages_assets_and_errors(self):
        for path in ('/', '/health', '/search', '/library', '/analytics',
                     '/papers/add', '/library/stats',
                     '/static/css/style.css', '/static/js/app.js', '/assets/plotly.js'):
            with self.subTest(path=path):
                with self.client.get(path) as response:
                    self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/not-found').status_code, 404)
        self.assertEqual(self.client.get('/library?year=oops').status_code, 400)
        self.assertEqual(self.client.post('/upload', data={}).status_code, 400)
        self.assertEqual(self.client.post('/upload', data={'csrf_token': 'é'}).status_code, 400)

    def test_live_http_startup(self):
        server = make_server('127.0.0.1', 0, self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/health', timeout=5) as response:
                self.assertIn(b'connected', response.read())
            with urlopen(base, timeout=5) as response:
                self.assertIn(b'Inspect the resources', response.read())
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_upload_analyze_correct_export_and_persist(self):
        pdf_data = self.pdf()
        response = self.upload(pdf_data)
        self.assertEqual(response.status_code, 302)
        location = response.headers['Location']
        paper_id = int(re.search(r'/papers/(\d+)', location).group(1))
        self.assertEqual(self.client.get(location).status_code, 200)
        duplicate = self.upload(pdf_data)
        self.assertEqual(duplicate.headers['Location'], location)
        self.assertEqual(len(list((self.root / 'uploads').glob('*.pdf'))), 1)

        def mixed_availability(resource):
            result = self.available(resource)
            if resource['category'] != 'code':
                result.update(status='missing', http_status=404)
            return result

        with patch('src.analysis.check_resource', side_effect=mixed_availability):
            response = self.client.post(location + '/analyze', data={
                'csrf_token': self.token(),
            })
            self.assertEqual(response.status_code, 302)
            self.wait(paper_id)

        with self.app.app_context():
            paper = get_paper(paper_id)
            resources = get_resources(paper_id)
        self.assertEqual(paper['score'], 50)
        self.assertEqual(paper['report']['denominator'], 2)
        self.assertEqual(paper['report']['accessible_count'], 1)
        self.assertEqual(len(resources), 2)
        self.assertTrue(all(resource['page'] == 1 for resource in resources))
        self.assertEqual(self.client.get(location).status_code, 200)
        self.assertEqual(self.client.get('/analytics').status_code, 200)

        code = next(r for r in resources if r['category'] == 'code')
        response = self.client.post(f"/resources/{code['id']}/category", data={
            'csrf_token': self.token(), 'category': 'other',
        })
        self.assertEqual(response.status_code, 302)
        exported = self.client.get(location + '/report.json')
        self.assertEqual(exported.json['paper']['score'], 50)
        self.assertNotIn('local_path', exported.json['paper'])
        self.assertEqual(self.client.get('/library.csv').status_code, 200)

        reopened = create_app(self.settings)
        with reopened.app_context():
            self.assertEqual(get_paper(paper_id)['score'], 50)

    def test_search_deduplicates_and_handles_provider_failure(self):
        paper = {'paper_id': '1234.5678', 'arxiv_id': '1234.5678',
                 'source': 'arXiv', 'title': 'Search result', 'authors': ['A. Author'],
                 'abstract': 'An example abstract', 'year': 2024}
        with patch('app.routes.discover', return_value=([paper], [])):
            for _ in range(2):
                self.assertEqual(self.client.get('/search?q=example').status_code, 200)
        with self.app.app_context():
            from src.database.db import list_papers
            self.assertEqual(len(list_papers()), 1)
        with patch('app.routes.discover', return_value=([], ['Provider unavailable'])):
            response = self.client.get('/search?q=example')
            self.assertIn(b'Provider unavailable', response.data)

    def test_provider_response_parsing(self):
        from src.paper.arxiv_client import search_arxiv
        from src.paper.semantic_scholar_client import search_semantic_scholar
        from unittest.mock import Mock
        atom = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
            <entry><id>http://arxiv.org/abs/1234.5678v1</id><title>Example paper</title>
            <summary>Example abstract</summary><published>2024-01-01T00:00:00Z</published>
            <author><name>Alice</name></author>
            <link href="http://arxiv.org/pdf/1234.5678v1" title="pdf" type="application/pdf"/>
            </entry></feed>'''
        response = Mock(content=atom)
        with patch('src.paper.arxiv_client.requests.get', return_value=response):
            with patch('src.paper.arxiv_client.time.sleep'):
                papers = search_arxiv('example', 1)
        self.assertEqual(papers[0]['arxiv_id'], '1234.5678')
        self.assertEqual(papers[0]['authors'], ['Alice'])
        self.assertTrue(papers[0]['pdf_url'].startswith('https://'))
        response.json.return_value = {'data': [{
            'paperId': 'example-id', 'title': 'Example paper', 'authors': [{'name': 'Bob'}],
            'openAccessPdf': {'url': 'https://example.org/paper.pdf'},
            'externalIds': {'ArXiv': '1234.5678'}, 'year': 2024,
        }]}
        with patch('src.paper.semantic_scholar_client.requests.get', return_value=response):
            papers = search_semantic_scholar('example', 1)
        self.assertEqual(papers[0]['paper_id'], 'example-id')
        self.assertEqual(papers[0]['authors'], ['Bob'])

    def test_manual_entry_and_abstract_fallback(self):
        response = self.client.post('/papers/add', data={
            'csrf_token': self.token(), 'title': '=Example manual paper',
            'authors': 'Alice; Bob', 'abstract': 'Code: https://github.com/example/repo',
        })
        self.assertEqual(response.status_code, 302)
        location = response.headers['Location']
        paper_id = int(location.rsplit('/', 1)[1])
        with patch('src.analysis.check_resource', side_effect=self.available):
            with self.app.app_context():
                start_analysis(paper_id, ['code'])
            self.wait(paper_id)
        with self.app.app_context():
            paper = get_paper(paper_id)
        self.assertEqual(paper['analysis_status'], 'partial')
        self.assertEqual(paper['report']['scope'], 'Abstract only')
        self.assertEqual(paper['score'], 100)
        self.assertIn(b"'=Example manual paper", self.client.get('/library.csv').data)

    def test_invalid_upload_and_manual_validation(self):
        response = self.upload(b'not a PDF')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(list((self.root / 'uploads').glob('*.pdf'))), 0)
        response = self.client.post('/papers/add', data={
            'csrf_token': self.token(), 'title': '', 'paper_url': 'javascript:alert(1)',
        })
        self.assertEqual(response.status_code, 400)
        self.app.config['MAX_CONTENT_LENGTH'] = 256
        response = self.client.post('/upload', data=b'x' * 1024,
                                    content_type='application/octet-stream')
        self.assertEqual(response.status_code, 413)

    def test_duplicate_job_and_restart_recovery(self):
        with self.app.app_context():
            paper_id = save_paper({'source': 'Manual', 'title': 'Queued paper'})
            with patch('src.analysis._executor.submit'):
                start_analysis(paper_id, ['code'])
                with self.assertRaises(ValueError):
                    start_analysis(paper_id, ['code'])
            from src.analysis import recover_interrupted_jobs
            recover_interrupted_jobs()
            self.assertEqual(latest_job(paper_id)['status'], 'failed')
            self.assertEqual(get_paper(paper_id)['analysis_status'], 'failed')

    def test_failed_reanalysis_preserves_previous_report(self):
        response = self.upload()
        location = response.headers['Location']
        paper_id = int(location.rsplit('/', 1)[1])
        with patch('src.analysis.check_resource', side_effect=self.available):
            with self.app.app_context():
                start_analysis(paper_id, ['code'])
            self.wait(paper_id)
        with self.assertLogs(self.app.logger, level='ERROR'), patch(
            'src.analysis._extract', side_effect=ValueError('Invalid PDF')
        ):
            with self.app.app_context():
                start_analysis(paper_id, ['code'])
            for _ in range(200):
                with self.app.app_context():
                    job = latest_job(paper_id)
                if job['status'] == 'failed':
                    break
                time.sleep(0.025)
            self.assertEqual(job['status'], 'failed')
        with self.app.app_context():
            self.assertEqual(get_paper(paper_id)['score'], 100)
        self.assertIn(b'Showing the previous report', self.client.get(location).data)

    def test_remote_download_failure_uses_abstract(self):
        with self.app.app_context():
            paper_id = save_paper({
                'source': 'Manual', 'title': 'Remote PDF',
                'pdf_url': 'https://example.org/paper.pdf',
                'abstract': 'Source code https://github.com/example/code',
            })
        with self.assertLogs(self.app.logger, level='WARNING'), patch(
            'src.analysis.download_pdf', side_effect=OSError('Unavailable')
        ):
            with patch('src.analysis.check_resource', side_effect=self.available):
                with self.app.app_context():
                    start_analysis(paper_id, ['code'])
                self.wait(paper_id)
        with self.app.app_context():
            paper = get_paper(paper_id)
        self.assertEqual(paper['analysis_status'], 'partial')
        self.assertEqual(paper['report']['scope'], 'Abstract only')

    def test_scoring_and_private_network_protection(self):
        self.assertIsNone(calculate_score([])['score'])
        self.assertEqual(calculate_score([
            {'url': 'https://example.org/1', 'category': 'code', 'status': 'accessible'},
            {'url': 'https://example.org/2', 'category': 'code', 'status': 'accessible'},
        ])['score'], 100)
        from src.checker import check_resource
        result = check_resource({'url': 'http://127.0.0.1/', 'category': 'other'})
        self.assertEqual(result['status'], 'blocked')

    def test_all_link_types_have_equal_weight_and_duplicates_count_once(self):
        links = [
            {'url': 'https://example.org/a', 'category': 'other', 'status': 'accessible'},
            {'url': 'https://example.org/b', 'category': 'code', 'status': 'accessible'},
            {'url': 'https://example.org/c', 'category': 'dataset', 'status': 'missing'},
            {'url': 'https://example.org/d', 'category': 'documentation', 'status': 'unresolved'},
        ]
        report = calculate_score(links + [links[0]], applicable=[])
        self.assertEqual(report['score'], 50)
        self.assertEqual(report['denominator'], 4)
        self.assertEqual(report['accessible_count'], 2)
        self.assertEqual(report['status_counts']['unresolved'], 1)
        for link in links:
            link['category'] = 'other'
        self.assertEqual(calculate_score(links)['score'], 50)
        self.assertEqual(calculate_score([links[0]])['score'], 100)
        self.assertEqual(calculate_score([links[2]])['score'], 0)

    def test_no_links_is_not_scored_and_analytics_remain_valid(self):
        response = self.client.post('/papers/add', data={
            'csrf_token': self.token(), 'title': 'Paper without URLs',
        })
        location = response.headers['Location']
        paper_id = int(location.rsplit('/', 1)[1])
        self.client.post(location + '/analyze', data={'csrf_token': self.token()})
        self.wait(paper_id)
        with self.app.app_context():
            self.assertIsNone(get_paper(paper_id)['score'])
        for path in (location, '/library', '/', '/analytics'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
        self.assertIn(b'Not scored', self.client.get(location).data)
        self.assertIsNone(self.client.get(location + '/report.json').json['paper']['score'])

    def test_more_than_sixty_links_are_all_checked(self):
        resources = [
            {'url': f'https://example.org/{i}', 'category': 'other', 'evidence': 'PDF link', 'page': 1}
            for i in range(65)
        ]
        extracted = {'resources': resources, 'warnings': [], 'text': 'Paper text', 'pages': 1}
        with self.app.app_context():
            paper_id = save_paper({'source': 'Manual', 'title': 'Many links'})
        with patch('src.analysis._extract', return_value=(extracted, 'Full PDF')):
            with patch('src.analysis.check_resource', side_effect=self.available) as checker:
                with self.app.app_context():
                    start_analysis(paper_id)
                self.wait(paper_id)
                self.assertEqual(checker.call_count, 65)
        with self.app.app_context():
            paper = get_paper(paper_id)
        self.assertEqual(paper['report']['denominator'], 65)
        self.assertEqual(paper['score'], 100)

    def test_old_scores_upgrade_without_rechecking_or_changing_check_time(self):
        from src.database.db import connection, save_analysis
        with self.app.app_context():
            paper_id = save_paper({'source': 'Manual', 'title': 'Old report'})
            resources = [self.available({'url': 'https://example.org/code', 'category': 'code'})]
            old_report = {'version': '1.0', 'score': 40, 'analyzed_at': '2020-01-01T00:00:00+00:00',
                          'scope': 'Full PDF', 'warnings': [], 'limitations': [], 'resource_count': 1,
                          'candidate_count': 1, 'applicable': ['code', 'dataset']}
            save_analysis(paper_id, resources, old_report, 'complete')
        with patch('src.analysis.check_resource') as checker:
            reopened = create_app(self.settings)
            checker.assert_not_called()
        with reopened.app_context():
            paper = get_paper(paper_id)
            resources = get_resources(paper_id)
            with connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual(paper['score'], 100)
        self.assertEqual(paper['report']['version'], '2.0')
        self.assertEqual(paper['report']['analyzed_at'], old_report['analyzed_at'])
        self.assertEqual(resources[0]['checked_at'], '2026-01-01T00:00:00+00:00')

    def test_tls_verification_remains_enabled(self):
        import os
        import ssl
        import certifi
        from src.checker.network import tls_context
        with patch.dict(os.environ, {'REQUESTS_CA_BUNDLE': certifi.where()}):
            context = tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertTrue(context.get_ca_certs())

    def test_certificate_failure_is_not_classified_as_missing(self):
        import ssl
        from src.checker import check_resource
        with patch('src.checker.fetch', side_effect=ssl.SSLCertVerificationError('Untrusted')):
            result = check_resource({'url': 'https://example.org/', 'category': 'other'})
        self.assertEqual(result['status'], 'unresolved')
        self.assertIn('Certificate verification failed', result['note'])

    def test_legacy_database_migration_preserves_papers(self):
        legacy = self.root / 'legacy.db'
        db = sqlite3.connect(legacy)
        db.executescript('''
            CREATE TABLE papers (
                id INTEGER PRIMARY KEY, source TEXT, external_id TEXT,
                title TEXT, authors TEXT, year INTEGER, abstract TEXT,
                paper_url TEXT, pdf_url TEXT, last_analyzed_at TEXT,
                analysis_status TEXT
            );
            INSERT INTO papers VALUES (
                1, 'arXiv', '1234.0001', 'Legacy paper', 'Alice; Bob',
                2020, '', NULL, NULL, NULL, 'pending'
            );
            CREATE TABLE resources (
                id INTEGER PRIMARY KEY, paper_id INTEGER, url TEXT,
                resource_type TEXT, accessibility_status TEXT,
                http_status INTEGER, error_message TEXT, checked_at TEXT
            );
            INSERT INTO resources VALUES (
                1, 1, 'https://github.com/example/legacy', 'Code', 'Accessible',
                200, NULL, '2020-01-01T00:00:00+00:00'
            );
        ''')
        db.close()
        init_db(legacy)
        db = sqlite3.connect(legacy)
        self.assertEqual(db.execute('SELECT title FROM papers').fetchone()[0], 'Legacy paper')
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        report = json.loads(db.execute('SELECT report FROM papers').fetchone()[0])
        self.assertEqual(report['score'], 100)
        self.assertEqual(report['scope'], 'Imported resource checks')
        db.close()
        self.assertTrue(list((self.root / 'backups').glob('*.db')))


if __name__ == '__main__':
    unittest.main()
