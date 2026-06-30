import os
import sqlite3
import numpy as np
import librosa
import soundfile as sf
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_cors import CORS
from sklearn.metrics.pairwise import cosine_similarity
import torch
import logging

# Setup proper error logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Optimize PyTorch CPU execution settings for Render deployment
torch.set_num_threads(1)

app = Flask(__name__)
app.secret_key = 'super_secret_voice_key_for_exam_portal'
CORS(app)

# Increase Flask request upload size limit to 20MB
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# We will use SpeechBrain ECAPA-TDNN for robust state-of-the-art speaker recognition embeddings
import torchaudio
from speechbrain.inference.speaker import EncoderClassifier

print("Loading SpeechBrain ECAPA-TDNN model...")
# Load pre-trained speaker recognition model
classifier = EncoderClassifier.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb", 
    run_opts={"device": "cpu"}
)
print("Model loaded successfully.")

# Database Initialization (SQLite only)
def init_db():
    try:
        with sqlite3.connect('database.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    voice_embedding BLOB
                )
            ''')
            conn.commit()
    except Exception as e:
        logger.exception("Database initialization failed")

init_db()

def process_audio_and_get_embedding(file_path):
    """
    Enhanced Audio Processing Pipeline using SpeechBrain ECAPA-TDNN:
    1. Load pure WAV audio & trim silence.
    2. Enforce VAD checks (RMS energy, volume, ZCR).
    3. Use SpeechBrain to extract a robust 192-dimensional x-vector embedding.
    """
    # VAD & Loading Pipeline
    wav, sr = librosa.load(file_path, sr=16000)
    
    # Trim silence from the beginning and end
    wav, _ = librosa.effects.trim(wav, top_db=20)
    
    if len(wav) == 0:
        raise ValueError("Audio contains only silence.")

    # Analyze Audio Energy (VAD fallback)
    rms_energy = librosa.feature.rms(y=wav).mean()
    
    peak_amplitude = np.max(np.abs(wav))
    if peak_amplitude < 0.08:
        raise ValueError(f"Audio volume is too low (Peak: {peak_amplitude:.3f}). Please speak clearly into the microphone.")

    if np.isnan(rms_energy) or rms_energy < 0.035: # Stricter threshold to strictly reject empty background noise
        raise ValueError(f"Audio is too quiet or mostly background noise (RMS: {rms_energy:.4f}). Please speak clearly.")
        
    zcr = librosa.feature.zero_crossing_rate(wav).mean()
    if zcr > 0.35: # Pure static noise usually has very high ZCR > 0.4
        raise ValueError(f"Audio resembles static or wind noise (ZCR: {zcr:.4f}). Please speak a clear phrase.")
        
    # Enforce a minimum duration of non-silent voice
    duration = librosa.get_duration(y=wav, sr=sr)
    if duration < 0.8:
        raise ValueError(f"Voice sample is too short ({duration:.2f}s) or contains too much silence. Please speak a full phrase.")
        
    # Deep Learning Feature Extraction using SpeechBrain
    # Convert numpy array to torch tensor
    import torch
    import gc
    signal = torch.from_numpy(wav).float().unsqueeze(0)
    
    # Extract Embeddings (Output shape: [1, 1, 192]) with no_grad to reduce memory footprint
    with torch.no_grad():
        embeddings = classifier.encode_batch(signal)
    
    # Squeeze to 1D numpy array
    embedding = embeddings.squeeze().detach().cpu().numpy()
    
    # L2 Normalize the embedding (ECAPA generally outputs normalized vectors already, but enforcing it ensures safe cosine similarity)
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    # Force garbage collection to free up memory from intermediate tensor states
    gc.collect()
    
    return embedding.astype(np.float32)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    audio_files = request.files.getlist('audio')
    
    if not username or not audio_files or len(audio_files) < 3:
        return jsonify({'error': 'Missing username or require exactly 3 audio samples for enrollment'}), 400
        



    try:
        embeddings = []
        for i, audio_file in enumerate(audio_files):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"register_{username}_{i}.wav")
            audio_file.save(file_path)
            file_size = os.path.getsize(file_path)

            
            # Step 1-7: Process audio and extract embedding
            embedding = process_audio_and_get_embedding(file_path)
            embeddings.append(embedding)
            
            if os.path.exists(file_path):
                os.remove(file_path)
                
        # Average the 3 embeddings to generate a stable user embedding
        avg_embedding = np.mean(embeddings, axis=0)
        
        # Normalize the averaged embedding!
        avg_norm = np.linalg.norm(avg_embedding)
        if avg_norm > 0:
            avg_embedding = avg_embedding / avg_norm

        
        # Save averaged embedding to Database
        with sqlite3.connect('database.db', timeout=10) as conn:
            c = conn.cursor()
            emb_bytes = avg_embedding.tobytes()
            c.execute("INSERT INTO users (username, voice_embedding) VALUES (?, ?)", (username, emb_bytes))
            conn.commit()
        
        return jsonify({'message': 'Registration successful. You can now login.'})
    except ValueError as ve:
        logger.warning(f"Registration validation failed for username '{username}': {ve}")
        return jsonify({'error': str(ve)}), 400
    except sqlite3.IntegrityError as ie:
        logger.warning(f"Registration unique constraint violated for username '{username}': {ie}")
        return jsonify({'error': 'Username already exists. Please choose another one or login.'}), 400
    except Exception as e:
        logger.exception(f"Unexpected error during registration for username '{username}'")
        return jsonify({'error': str(e)}), 500

@app.route('/authenticate', methods=['POST'])
def authenticate():
    username = request.form.get('username')
    audio_file = request.files.get('audio')
    
    if not username or not audio_file:
        return jsonify({'error': 'Missing username or audio'}), 400
        

    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"login_{username}.wav")
    audio_file.save(file_path)
    file_size = os.path.getsize(file_path)

    
    try:
        # Retrieve stored embedding mask from DB
        with sqlite3.connect('database.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT voice_embedding FROM users WHERE username = ?", (username,))
            row = c.fetchone()
        
        if not row:
            logger.warning(f"Authentication failed - user '{username}' not found in database")
            return jsonify({'error': 'User not found. Please register first.'}), 404
            
        stored_emb_bytes = row[0]
        if isinstance(stored_emb_bytes, memoryview):
            stored_emb_bytes = stored_emb_bytes.tobytes()
        stored_embedding = np.frombuffer(stored_emb_bytes, dtype=np.float32)

        # Extract embedding from recent test audio
        test_embedding = process_audio_and_get_embedding(file_path)
        
        # Ensure sizes match (in case old DB entry used 240 dims and new code uses 240 dims!)
        if len(stored_embedding) != len(test_embedding):
             logger.error(f"Embedding size mismatch for user '{username}' (stored: {len(stored_embedding)}, test: {len(test_embedding)})")
             return jsonify({'error': 'Audio embedding dimensions changed. Please re-register your voice.'}), 400

        # Compute Cosine Similarity between stored embedding and test embedding
        similarity = cosine_similarity(stored_embedding.reshape(1, -1), test_embedding.reshape(1, -1))[0][0]
        
        # SpeechBrain ECAPA-TDNN Embeddings typically score > 0.40 for same speaker 
        # and < 0.25 for different speakers in cosine similarity.
        # We use a threshold of 0.45 for strict authentication to prevent familial false accepts.
        threshold = 0.45

        # Authentication Decision based on Threshold
        if similarity >= threshold:
            session['authenticated'] = True
            session['username'] = username
            logger.info(f"Authentication successful for user '{username}' (similarity: {similarity:.4f})")
            return jsonify({
                'message': 'Authentication successful. Redirecting to Exam Portal...', 
                'similarity': float(similarity), 
                'redirect': url_for('portal')
            })
        else:
            logger.warning(f"Authentication failed for user '{username}' due to voice mismatch (similarity: {similarity:.4f})")
            return jsonify({
                'error': f'Authentication Failed. Voice mismatch (Score: {similarity:.2f}). Please try again.', 
                'similarity': float(similarity)
            }), 401
    
    except ValueError as ve:
        logger.warning(f"Authentication validation failed for user '{username}': {ve}")
        return jsonify({'error': str(ve)}), 400        
    except Exception as e:
        logger.exception(f"Unexpected error during authentication for user '{username}'")
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@app.route('/portal')
def portal():
    # Only allow access if authenticated
    if not session.get('authenticated'):
        return redirect(url_for('index'))
    return render_template('portal.html', username=session.get('username'))

@app.route('/start_test')
def start_test():
    # Only allow access if authenticated
    if not session.get('authenticated'):
        return redirect(url_for('index'))
    return render_template('test.html')

@app.route('/submit_test', methods=['POST'])
def submit_test():
    if not session.get('authenticated'):
        return redirect(url_for('index'))
    return render_template('result.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Run the Flask App (use_reloader=False prevents unexpected restarts on Windows Store Python)
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
