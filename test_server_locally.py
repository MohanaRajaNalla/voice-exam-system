import requests
import numpy as np
import soundfile as sf
import os
import time

def create_valid_wav(filename, data, sr=16000):
    sf.write(filename, data, sr)

# 1. Silent file
print("Creating silent file...")
create_valid_wav("test_silent.wav", np.zeros(16000 * 4), 16000)

# 2. Quiet noise file (simulating empty room background noise)
print("Creating quiet noise file...")
create_valid_wav("test_noise.wav", np.random.randn(16000 * 4) * 0.005, 16000)

# 3. Loud noise file
print("Creating loud noise file...")
create_valid_wav("test_loud.wav", np.random.randn(16000 * 4) * 0.5, 16000)

url_reg = "http://127.0.0.1:5000/register"
url_auth = "http://127.0.0.1:5000/authenticate"

def test_register(username, filename):
    print(f"\n--- Testing Registration for {username} with {filename} ---")
    files = [
        ('audio', (filename, open(filename, 'rb'), 'audio/wav')),
        ('audio', (filename, open(filename, 'rb'), 'audio/wav')),
        ('audio', (filename, open(filename, 'rb'), 'audio/wav'))
    ]
    data = {'username': username}
    r = requests.post(url_reg, files=files, data=data)
    print("Status:", r.status_code)
    try:
        print("Response:", r.json())
    except:
        print("Response Text:", r.text)

def test_auth(username, filename):
    print(f"\n--- Testing Auth for {username} with {filename} ---")
    files = {'audio': (filename, open(filename, 'rb'), 'audio/wav')}
    data = {'username': username}
    r = requests.post(url_auth, files=files, data=data)
    print("Status:", r.status_code)
    try:
        print("Response:", r.json())
    except:
        print("Response Text:", r.text)

test_register("user_silent", "test_silent.wav")
test_register("user_noise", "test_noise.wav")
test_register("user_loud", "test_loud.wav")

test_auth("user_noise", "test_noise.wav")
test_auth("user_noise", "test_loud.wav")

print("\nDone testing.")
