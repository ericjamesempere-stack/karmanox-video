"""Patch conservateur pour KarmaClip app.py : export et restauration des clips WAN.
Exécuter dans le dossier contenant app.py : python KarmaClip_sauvegarde_patch.py
Crée app.py.bak avant modification.
"""
from pathlib import Path
import shutil
p = Path('app.py')
s = p.read_text(encoding='utf-8')
marker = "    clips = st.session_state.kc_chain_clips\n    if clips:\n"
assert s.count(marker) == 1, 'Version app.py différente : aucune modification effectuée.'
insert = '''    # Sauvegarde et restauration locales des séquences WAN.
    # L'utilisateur garde son ZIP sur son téléphone, même si Render redémarre.
    with st.expander('💾 Sauvegarder / restaurer mes scènes WAN'):
        restore_zip = st.file_uploader('Restaurer un ZIP KarmaClip', type=['zip'], key='kc_chain_restore_zip')
        if restore_zip and st.button('📂 Restaurer les vidéos du ZIP', key='kc_chain_restore_button'):
            try:
                with zipfile.ZipFile(io.BytesIO(restore_zip.getvalue())) as z:
                    names = sorted(n for n in z.namelist() if re.fullmatch(r'scene_\\d{3}\\.mp4', n))
                    if not names or len(names) > 300:
                        raise ValueError('Aucune scène valide ou trop de scènes dans le ZIP.')
                    if any(z.getinfo(n).file_size > 250 * 1024 * 1024 for n in names):
                        raise ValueError('Une vidéo dépasse 250 Mo.')
                    restored = [z.read(n) for n in names]
                    if any(len(v) < 1024 for v in restored):
                        raise ValueError('Une vidéo semble vide ou invalide.')
                restored_frames = [photo_bytes] if photo_bytes else []
                for video_data in restored:
                    restored_frames.append(kc_chain_last_frame(video_data))
                st.session_state.kc_chain_clips = restored
                st.session_state.kc_chain_frames = restored_frames
                st.session_state.pop('kc_chain_config', None)
                st.session_state.pop('kc_chain_montage', None)
                st.success(f'{len(restored)} scène(s) restaurée(s). Montage possible immédiatement.')
                st.info('Pour poursuivre la génération WAN, recommence une série avec les mêmes paramètres : le ZIP restaure les vidéos, mais pas la configuration d’origine.')
                st.rerun()
            except Exception as exc:
                st.error('Restauration impossible : ' + str(exc))
    clips = st.session_state.kc_chain_clips
    if clips:
        backup_buffer = io.BytesIO()
        with zipfile.ZipFile(backup_buffer, 'w', compression=zipfile.ZIP_STORED) as z:
            for index, video_data in enumerate(clips, 1):
                z.writestr(f'scene_{index:03d}.mp4', video_data)
            z.writestr('LISEZ_MOI.txt', 'Sauvegarde des scènes vidéo KarmaClip WAN.\\n')
        st.download_button('💾 Télécharger mes scènes (ZIP)', backup_buffer.getvalue(),
            file_name='KarmaClip_scenes_WAN.zip', mime='application/zip',
            key='kc_chain_save_zip', use_container_width=True)
'''
# Explicitly preserve existing WAN logic; restore does not pretend to recover settings.
shutil.copy2(p, p.with_name('app.py.bak'))
p.write_text(s.replace(marker, insert), encoding='utf-8')
print('Patch appliqué. Sauvegarde : app.py.bak')
