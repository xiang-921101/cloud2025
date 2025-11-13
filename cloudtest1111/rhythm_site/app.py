from flask import Flask, render_template, request, jsonify, session
import json, os, random
from mutagen.mp3 import MP3
from moviepy import TextClip, concatenate_videoclips, AudioFileClip
from flask_session import Session
import threading
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

UPLOAD_FOLDER = 'static/uploads'
VIDEO_FOLDER = 'static/videos'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)

# 載入動作資料庫
with open('static/data/actions.json', 'r', encoding='utf-8') as f:
    ACTIONS = json.load(f)

progress_store = {}  # 儲存影片生成進度 {session_id: percent}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    files = request.files.getlist('files')
    uploaded_files = []
    for f in files:
        filename = f.filename
        path = os.path.join(UPLOAD_FOLDER, filename)
        f.save(path)
        uploaded_files.append(filename)
    return jsonify({"uploaded": uploaded_files})

@app.route('/get_actions')
def get_actions():
    section = request.args.get('section', 'warmup')
    level = request.args.get('level', 'low')
    if section in ACTIONS and level in ACTIONS[section]:
        return jsonify(ACTIONS[section][level])
    return jsonify([])

@app.route('/analyze', methods=['POST'])
def analyze():
    difficulty = request.form.get('difficulty')
    duration = float(request.form.get('duration', 0))
    target_seconds = duration * 60

    # 音樂清單處理
    music_list_raw = request.form.get('musicList', '')
    music_names = [m.strip() for m in music_list_raw.split(',') if m.strip()]
    music_list = []
    total_length = 0
    for name in music_names:
        path = os.path.join(UPLOAD_FOLDER, name)
        try:
            audio = MP3(path)
            dur = int(audio.info.length)
        except:
            dur = 180
        music_list.append({'name': name, 'duration': dur})
        total_length += dur

    final_music_list = []
    if total_length <= target_seconds:
        current_time = 0
        idx = 0
        while current_time < target_seconds:
            song = music_list[idx % len(music_list)]
            final_music_list.append(song)
            current_time += song['duration']
            idx += 1
    else:
        shuffled = music_list[:]
        random.shuffle(shuffled)
        current_time = 0
        for song in shuffled:
            if current_time + song['duration'] <= target_seconds:
                final_music_list.append(song)
                current_time += song['duration']

    actions_list = request.form.getlist('actions')

    form_data = {
        "difficulty": difficulty,
        "duration": duration,
        "music_list": final_music_list,
        "actions": actions_list
    }

    return render_template(
        'analyze.html',
        form_data_json=json.dumps(form_data, ensure_ascii=False)
    )

@app.route('/analyze/result', methods=['POST'])
def analyze_result():
    data = request.get_json()
    unique_music = []
    seen = set()
    for m in data.get("music_list", []):
        if m["name"] not in seen:
            unique_music.append(m)
            seen.add(m["name"])
    return jsonify({
        "difficulty": data.get("difficulty"),
        "duration": data.get("duration"),
        "music_list": unique_music,
        "actions": data.get("actions")
    })

@app.route('/results')
def results():
    return render_template('results.html')

# ================== 影片合成 ==================
# GET: 顯示頁面 / POST: 生成影片
@app.route('/compose', methods=['GET', 'POST'])
def compose_page_or_video():
    if request.method == 'GET':
        return render_template('compose.html')

    # POST: 生成影片
    data = request.get_json()
    session_id = str(uuid.uuid4())
    progress_store[session_id] = 0

    def background_task(data, session_id):
        clips = []
        w, h = 640, 360
        actionTime = 20
        restTime = 10
        actions = data.get("actions", [])
        music_list = data.get("music_list", [])

        for i, action in enumerate(actions):
            sec, name = action.split("|")
            sec = sec.strip()
            name = name.strip()
            duration = restTime if name == "休息" else actionTime
            txt = TextClip(
                text=name if name != "休息" else "休息",
                font_size=40,
                color='white',
                size=(w, h),
                method='caption',
                bg_color='black' if name != "休息" else 'gray'
            ).with_duration(duration)
            clips.append(txt)
            progress_store[session_id] = int((i+1)/len(actions)*50)

        final_clip = concatenate_videoclips(clips)

        if music_list:
            import moviepy as mpe
            audio_clips = []
            total_duration = final_clip.duration
            current_time = 0
            idx = 0
            while current_time < total_duration:
                song = music_list[idx % len(music_list)]
                path = os.path.join(UPLOAD_FOLDER, song['name'])
                audio_clip = AudioFileClip(path)
                if current_time + audio_clip.duration > total_duration:
                    end_time = total_duration - current_time
                    if end_time > 0:
                        audio_clip = audio_clip.subclipped(0, end_time)
                    else:
                        break  # 已經到總時長，跳出迴圈


                audio_clips.append(audio_clip)
                current_time += audio_clip.duration
                idx += 1
                progress_store[session_id] = 50 + int(current_time/total_duration*50)

            final_audio = mpe.concatenate_audioclips(audio_clips)
            final_clip = final_clip.with_audio(final_audio)

        output_path = os.path.join(VIDEO_FOLDER, f"workout_{session_id}.mp4")
        final_clip.write_videofile(output_path, fps=24)
        progress_store[session_id] = 100

    thread = threading.Thread(target=background_task, args=(data, session_id))
    thread.start()

    return jsonify({"session_id": session_id})

@app.route('/compose/progress/<session_id>')
def compose_progress(session_id):
    progress = progress_store.get(session_id, 0)
    return jsonify({"progress": progress})

@app.route('/workout')
def workout():
    return render_template("workout.html")

if __name__ == '__main__':
    app.run(debug=True)
