document.addEventListener('DOMContentLoaded', () => {
    // Tab Switching Logic
    const tabs = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            
            tab.classList.add('active');
            document.getElementById(`${tab.dataset.tab}-section`).classList.add('active');
        });
    });

    // Audio Recording Variables
    let audioContext;
    
    // Login state
    let loginBlob = null;
    
    // Register state
    let registerBlobs = [];
    const MAX_SAMPLES = 3;

    // Helper to generate proper WAV Blob from AudioBuffer
    function bufferToWav(abuffer) {
        let numOfChan = abuffer.numberOfChannels,
            length = abuffer.length * numOfChan * 2 + 44,
            buffer = new ArrayBuffer(length),
            view = new DataView(buffer),
            channels = [], i, sample,
            offset = 0,
            pos = 0;

        function setUint16(data) {
            view.setUint16(pos, data, true);
            pos += 2;
        }

        function setUint32(data) {
            view.setUint32(pos, data, true);
            pos += 4;
        }

        setUint32(0x46464952);                         // "RIFF"
        setUint32(length - 8);                         // file length - 8
        setUint32(0x45564157);                         // "WAVE"

        setUint32(0x20746d66);                         // "fmt " chunk
        setUint32(16);                                 // length = 16
        setUint16(1);                                  // PCM (uncompressed)
        setUint16(numOfChan);
        setUint32(abuffer.sampleRate);
        setUint32(abuffer.sampleRate * 2 * numOfChan); // avg. bytes/sec
        setUint16(numOfChan * 2);                      // block-align
        setUint16(16);                                 // 16-bit

        setUint32(0x61746164);                         // "data" - chunk
        setUint32(length - pos - 4);                   // chunk length

        for (i = 0; i < abuffer.numberOfChannels; i++)
            channels.push(abuffer.getChannelData(i));

        while (pos < length) {
            for (i = 0; i < numOfChan; i++) {
                sample = Math.max(-1, Math.min(1, channels[i][offset])); // clamp
                sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767)|0; // scale
                view.setInt16(pos, sample, true);
                pos += 2;
            }
            offset++
        }
        return new Blob([buffer], {type: "audio/wav"});
    }
    
    async function startRecording(onStopCallback, duration = 4000) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            let mediaRecorder = new MediaRecorder(stream);
            let audioChunks = [];

            mediaRecorder.addEventListener("dataavailable", event => {
                audioChunks.push(event.data);
            });

            mediaRecorder.addEventListener("stop", async () => {
                const webmBlob = new Blob(audioChunks);
                
                // Decode WebM to AudioBuffer and encode to pure PCM WAV
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const arrayBuffer = await webmBlob.arrayBuffer();
                const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
                const wavBlob = bufferToWav(audioBuffer);
                
                stream.getTracks().forEach(track => track.stop());
                onStopCallback(wavBlob);
            });

            mediaRecorder.start();
            
            // Automatically stop recording after `duration` ms
            setTimeout(() => {
                if (mediaRecorder.state === "recording") {
                    mediaRecorder.stop();
                }
            }, duration);
            
            return true;
        } catch (err) {
            console.error("Error accessing microphone:", err);
            alert("Microphone access is required to use this system.");
            return false;
        }
    }

    /* ---------------- LOGIN LOGIC ---------------- */
    const loginMicBtn = document.getElementById('login-mic-btn');
    const loginStatus = document.getElementById('login-status');
    const loginSubmitBtn = document.getElementById('login-submit-btn');
    const loginMessage = document.getElementById('login-message');

    loginMicBtn.addEventListener('click', async () => {
        if (loginMicBtn.classList.contains('recording')) return;
        
        const success = await startRecording((blob) => {
            loginBlob = blob;
            loginMicBtn.classList.remove('recording');
            loginStatus.textContent = "Voice Recorded Successfully";
            loginStatus.style.color = 'var(--success)';
            loginSubmitBtn.disabled = false;
        }, 4000); // Record for 4 seconds

        if (success) {
            loginMicBtn.classList.add('recording');
            loginStatus.textContent = "Recording... Speak Now (4s)";
            loginStatus.style.color = 'var(--error)';
            loginSubmitBtn.disabled = true;
            loginMessage.style.display = 'none';
        }
    });

    loginSubmitBtn.addEventListener('click', async () => {
        const username = document.getElementById('login-username').value.trim();
        
        if (!username) {
            showMessage(loginMessage, "Please enter your username", 'error');
            return;
        }
        if (!loginBlob) {
            showMessage(loginMessage, "Please record your voice first", 'error');
            return;
        }

        loginSubmitBtn.disabled = true;
        loginSubmitBtn.textContent = "Authenticating...";

        const formData = new FormData();
        formData.append('username', username);
        formData.append('audio', loginBlob, 'login.wav');

        let response;
        try {
            response = await fetch('/authenticate', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();

            if (response.ok) {
                showMessage(loginMessage, `${data.message} (Sim: ${data.similarity.toFixed(2)})`, 'success');
                setTimeout(() => {
                    window.location.href = data.redirect;
                }, 1500);
            } else {
                showMessage(loginMessage, data.error, 'error');
            }
        } catch (error) {
            showMessage(loginMessage, "Server communication error", 'error');
        } finally {
            if (!response?.ok) {
                loginSubmitBtn.disabled = false;
                loginSubmitBtn.textContent = "Authenticate via Voice";
            }
        }
    });

    /* ---------------- REGISTER LOGIC ---------------- */
    const registerMicBtn = document.getElementById('register-mic-btn');
    const registerStatus = document.getElementById('register-status');
    const registerSubmitBtn = document.getElementById('register-submit-btn');
    const registerMessage = document.getElementById('register-message');

    registerMicBtn.addEventListener('click', async () => {
        if (registerMicBtn.classList.contains('recording') || registerBlobs.length >= MAX_SAMPLES) return;
        
        const currentSample = registerBlobs.length + 1;
        
        const success = await startRecording((blob) => {
            registerBlobs.push(blob);
            registerMicBtn.classList.remove('recording');
            
            // Update UI indicators
            document.getElementById(`ind-${currentSample}`).classList.remove('current');
            document.getElementById(`ind-${currentSample}`).classList.add('done');
            
            if (registerBlobs.length < MAX_SAMPLES) {
                registerStatus.textContent = `Record Sample ${registerBlobs.length + 1}`;
                registerStatus.style.color = 'var(--text-muted)';
                document.getElementById(`ind-${registerBlobs.length + 1}`).classList.add('current');
                
            } else {
                registerStatus.textContent = "All 3 Samples Recorded!";
                registerStatus.style.color = 'var(--success)';
                registerSubmitBtn.disabled = false;
                registerMicBtn.style.opacity = '0.5';
                registerMicBtn.style.cursor = 'not-allowed';
            }
        }, 3000); // 3 seconds per enrollment sample

        if (success) {
            registerMicBtn.classList.add('recording');
            registerStatus.textContent = `Recording Sample ${currentSample}... (3s)`;
            registerStatus.style.color = 'var(--error)';
            document.getElementById(`ind-${currentSample}`).classList.add('current');
            registerMessage.style.display = 'none';
        }
    });

    registerSubmitBtn.addEventListener('click', async () => {
        const username = document.getElementById('register-username').value.trim();
        
        if (!username) {
            showMessage(registerMessage, "Please choose a username", 'error');
            return;
        }
        if (registerBlobs.length < MAX_SAMPLES) {
            showMessage(registerMessage, `Please record all ${MAX_SAMPLES} samples`, 'error');
            return;
        }

        registerSubmitBtn.disabled = true;
        registerSubmitBtn.textContent = "Extracting Embeddings...";

        const formData = new FormData();
        formData.append('username', username);
        registerBlobs.forEach((blob, i) => {
            formData.append('audio', blob, `register_${i}.wav`);
        });

        try {
            const response = await fetch('/register', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();

            if (response.ok) {
                showMessage(registerMessage, data.message, 'success');
                // Reset form
                registerBlobs = [];
                document.getElementById('register-username').value = '';
                document.querySelectorAll('.indicator').forEach(ind => {
                    ind.classList.remove('done', 'current');
                });
                document.getElementById('ind-1').classList.add('current');
                registerStatus.textContent = "Record Sample 1";
                registerStatus.style.color = 'var(--text-muted)';
                registerSubmitBtn.textContent = "Enroll Voice Biometrics";
                registerMicBtn.style.opacity = '1';
                registerMicBtn.style.cursor = 'pointer';
                
                // Switch to login tab after brief delay
                setTimeout(() => {
                    document.querySelector('.tab-btn[data-tab="login"]').click();
                    document.getElementById('login-username').value = username;
                }, 2000);
            } else {
                showMessage(registerMessage, data.error, 'error');
                registerSubmitBtn.disabled = false;
                registerSubmitBtn.textContent = "Enroll Voice Biometrics";
            }
        } catch (error) {
            showMessage(registerMessage, "Server communication error", 'error');
            registerSubmitBtn.disabled = false;
            registerSubmitBtn.textContent = "Enroll Voice Biometrics";
        }
    });

    // Helper Function
    function showMessage(element, text, type) {
        element.textContent = text;
        element.className = `message-box ${type}`;
        element.style.display = 'block';
    }
});
