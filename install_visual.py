"""Run once in the same folder as app.py and karma_visual.py.
Creates app.py.bak and adds the visual studio without deleting existing sections.
"""
from pathlib import Path
import ast
p=Path('app.py')
s=p.read_text(encoding='utf-8')
if 'from karma_visual import render as render_visual_studio' not in s:
    anchor="st.set_page_config(page_title='KarmaClip Studio', page_icon='🎬', layout='centered')"
    if anchor not in s:
        raise SystemExit('App version not recognized. No file modified.')
    s=s.replace(anchor,anchor+'\nfrom karma_visual import render as render_visual_studio\nrender_visual_studio()',1)
    anchor2='photo_bytes = None\nif photo:'
    if anchor2 not in s:
        raise SystemExit('Photo integration not recognized. No file modified.')
    s=s.replace(anchor2,"photo_bytes = st.session_state.get('kv_video_start_image')\nif photo:",1)
    ast.parse(s)
    Path('app.py.bak').write_text(p.read_text(encoding='utf-8'),encoding='utf-8')
    p.write_text(s,encoding='utf-8')
    print('OK: studio visuel added, backup saved as app.py.bak')
else:
    print('Already installed; no changes')
