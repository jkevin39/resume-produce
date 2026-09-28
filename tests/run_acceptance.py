"""Run synthetic regressions, retaining representative exact HTML and matching Spec."""
import argparse
import json
import io
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from resume_app.rendering import ResumeRenderer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'artifacts'/('v07-regression-'+datetime.now().strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--keep-all',action='store_true',help='Retain every render for debugging; prefer --output under /tmp')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    original=ResumeRenderer.render_document
    guard=threading.Lock();counter=0;retained=[];modes=set()
    def preserve(self,context,editable=False):
        nonlocal counter
        html=original(self,context,editable)
        with guard:
            counter+=1
            mode='editable' if editable else 'static'
            if not args.keep_all and mode in modes:
                return html
            modes.add(mode)
            folder=args.output/(f'render-{counter:03d}' if args.keep_all else f'render-{mode}');folder.mkdir()
            retained.append({'mode':mode,'html':str(folder.relative_to(args.output)/'resume.html'),'spec':str(folder.relative_to(args.output)/'resume-spec.json')})
            (folder/'resume.html').write_text(html,encoding='utf-8')
            (folder/'resume-spec.json').write_text(json.dumps(context.spec,ensure_ascii=False,indent=2),encoding='utf-8')
        return html
    with patch.object(ResumeRenderer,'render_document',preserve):
        suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py',top_level_dir=str(Path(__file__).parent.parent))
        log=io.StringIO()
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (args.output/'test-results.txt').write_text(log.getvalue(),encoding='utf-8')
    summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'render_count':counter,'html_count':len(retained),'capture_mode':'all' if args.keep_all else 'representative','artifacts':retained}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({'artifact_dir':str(args.output.resolve()),**summary}))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
