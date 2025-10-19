#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
電影播放伺服器
作者: MiniMax Agent
功能: 雙網頁架構的影片播放系統，支援跨設備控制
"""

import os
import json
import re
from flask import Flask, render_template, jsonify, send_from_directory, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import threading
import time
from pathlib import Path

app = Flask(__name__)
app.config['SECRET_KEY'] = '20252025202520252025202520252025'
socketio = SocketIO(app, cors_allowed_origins="*")

# 配置
DATA_DIR = './data'
PORT = 5000

# 全域狀態 - 支援多房間
rooms_state = {}  # 房間狀態字典
connected_clients = {}  # 客戶端連接信息

def get_room_state(room_id):
    """獲取或創建房間狀態"""
    if room_id not in rooms_state:
        rooms_state[room_id] = {
            'current_movie': None,
            'current_episode': None,
            'is_playing': False,
            'current_time': 0,
            'volume': 1.0,
            'players': [],
            'controllers': [],
            'created_at': time.time()
        }
    return rooms_state[room_id]

def add_client_to_room(room_id, client_id, client_type):
    """添加客戶端到房間"""
    room_state = get_room_state(room_id)
    if client_type == 'player' and client_id not in room_state['players']:
        room_state['players'].append(client_id)
    elif client_type == 'controller' and client_id not in room_state['controllers']:
        room_state['controllers'].append(client_id)
    
    connected_clients[client_id] = {
        'room': room_id,
        'type': client_type,
        'joined_at': time.time()
    }

def remove_client_from_room(client_id):
    """從房間移除客戶端"""
    if client_id in connected_clients:
        client_info = connected_clients[client_id]
        room_id = client_info['room']
        client_type = client_info['type']
        
        if room_id in rooms_state:
            room_state = rooms_state[room_id]
            if client_type == 'player' and client_id in room_state['players']:
                room_state['players'].remove(client_id)
            elif client_type == 'controller' and client_id in room_state['controllers']:
                room_state['controllers'].remove(client_id)
            
            # 如果房間沒有客戶端了，清理房間（可選）
            if not room_state['players'] and not room_state['controllers']:
                # 保留房間狀態 30 分鐘，以防客戶端重新連接
                pass
        
        del connected_clients[client_id]

def natural_sort_key(episode_name):
    """
    自然排序鍵，支援多種命名格式：
    - 純數字：1, 2, 3...
    - 中文數字：第1集, 第2集...
    - 混合格式：電影名1, 電影名2...
    """
    # 提取數字部分進行排序
    numbers = re.findall(r'\d+', episode_name)
    if numbers:
        # 使用第一個找到的數字作為排序依據
        main_number = int(numbers[0])
        return (main_number, episode_name)
    else:
        # 沒有數字的情況，按字母順序排序
        return (float('inf'), episode_name)

def scan_movies():
    """掃描影片目錄，建立影片庫"""
    movies = {}
    
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        return movies
    
    # 掃描目錄結構
    for movie_dir in os.listdir(DATA_DIR):
        movie_path = os.path.join(DATA_DIR, movie_dir)
        if os.path.isdir(movie_path):
            # 電影資訊
            movie_info = {
                'name': movie_dir,
                'thumbnail': None,
                'episodes': []
            }
            
            # 檢查電影主縮圖
            thumbnail_path = os.path.join(movie_path, '縮圖.jpg')
            if os.path.exists(thumbnail_path):
                movie_info['thumbnail'] = f'data/{movie_dir}/縮圖.jpg'
            
            # 掃描集數
            for file in os.listdir(movie_path):
                if file.endswith('.mp4'):
                    episode_name = file[:-4]  # 移除 .mp4 副檔名
                    episode_info = {
                        'name': episode_name,
                        'file': f'data/{movie_dir}/{file}',
                        'thumbnail': None,
                        'display_name': episode_name  # 顯示名稱
                    }
                    
                    # 為純數字檔名創建更友好的顯示名稱
                    if episode_name.isdigit():
                        episode_info['display_name'] = f'第 {episode_name} 集'
                    
                    # 檢查集數縮圖
                    episode_thumbnail = os.path.join(movie_path, f'{episode_name}.jpg')
                    if os.path.exists(episode_thumbnail):
                        episode_info['thumbnail'] = f'data/{movie_dir}/{episode_name}.jpg'
                    
                    movie_info['episodes'].append(episode_info)
            
            # 使用智能排序
            movie_info['episodes'].sort(key=lambda x: natural_sort_key(x['name']))
            movies[movie_dir] = movie_info
    
    # 處理根目錄下的散亂影片文件（如：1.mp4, 2.mp4）
    root_videos = []
    for file in os.listdir(DATA_DIR):
        if file.endswith('.mp4') and os.path.isfile(os.path.join(DATA_DIR, file)):
            episode_name = file[:-4]
            episode_info = {
                'name': episode_name,
                'file': f'data/{file}',
                'thumbnail': None,
                'display_name': episode_name
            }
            
            # 為純數字檔名創建更友好的顯示名稱
            if episode_name.isdigit():
                episode_info['display_name'] = f'第 {episode_name} 集'
            
            # 檢查縮圖
            episode_thumbnail = os.path.join(DATA_DIR, f'{episode_name}.jpg')
            if os.path.exists(episode_thumbnail):
                episode_info['thumbnail'] = f'data/{episode_name}.jpg'
            
            root_videos.append(episode_info)
    
    # 如果有根目錄影片，創建一個特殊的"未分類影片"分類
    if root_videos:
        root_videos.sort(key=lambda x: natural_sort_key(x['name']))
        movies['未分類影片'] = {
            'name': '未分類影片',
            'thumbnail': None,
            'episodes': root_videos
        }
    
    return movies

# 路由設定
@app.route('/')
def index():
    """主頁 - 顯示可用的介面"""
    return render_template('index.html')

@app.route('/player')
def player():
    """播放器頁面（網頁A）"""
    return render_template('player.html')

@app.route('/control')
def control():
    """控制台頁面（網頁B）"""
    movies = scan_movies()
    return render_template('control.html', movies=movies)

@app.route('/api/movies')
def api_movies():
    """獲取影片列表 API"""
    movies = scan_movies()
    return jsonify(movies)

@app.route('/rooms')
def rooms_page():
    """房間管理頁面"""
    return render_template('rooms.html')

@app.route('/player/<room_id>')
def player_with_room(room_id):
    """指定房間的播放器頁面"""
    return render_template('player.html', room_id=room_id)

@app.route('/control/<room_id>')
def control_with_room(room_id):
    """指定房間的控制台頁面"""
    movies = scan_movies()
    return render_template('control.html', movies=movies, room_id=room_id)

@app.route('/api/rooms')
def api_rooms():
    """獲取所有房間信息"""
    room_list = []
    for room_id, state in rooms_state.items():
        room_info = {
            'id': room_id,
            'current_movie': state['current_movie'],
            'current_episode': state['current_episode'],
            'is_playing': state['is_playing'],
            'players_count': len(state['players']),
            'controllers_count': len(state['controllers']),
            'created_at': state['created_at']
        }
        room_list.append(room_info)
    
    return jsonify({
        'rooms': room_list,
        'total_clients': len(connected_clients)
    })

@app.route('/api/state/<room_id>')
def api_room_state(room_id):
    """獲取指定房間的狀態"""
    room_state = get_room_state(room_id)
    return jsonify(room_state)

@app.route('/data/<path:filename>')
def serve_media(filename):
    """提供影片和縮圖檔案"""
    return send_from_directory(DATA_DIR, filename)

# WebSocket 事件處理
# WebSocket 事件處理
@socketio.on('connect')
def handle_connect():
    print(f'客戶端已連接: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'客戶端已斷線: {request.sid}')
    remove_client_from_room(request.sid)
    # 廣播房間列表更新
    socketio.emit('rooms_update')

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data.get('room', 'default')
    client_type = data.get('type', 'unknown')  # 'player' 或 'controller'
    
    join_room(room_id)
    add_client_to_room(room_id, request.sid, client_type)
    
    room_state = get_room_state(room_id)
    emit('state_update', room_state)
    emit('room_joined', {'room': room_id, 'type': client_type})
    
    # 廣播房間列表更新給所有客戶端
    socketio.emit('rooms_update')
    
    print(f'客戶端 {request.sid} 以 {client_type} 身份加入房間: {room_id}')

@socketio.on('leave_room')
def handle_leave_room(data):
    room_id = data.get('room', 'default')
    leave_room(room_id)
    remove_client_from_room(request.sid)
    
    # 廣播房間列表更新
    socketio.emit('rooms_update')
    
    print(f'客戶端 {request.sid} 離開房間: {room_id}')

@socketio.on('play_episode')
def handle_play_episode(data):
    """播放指定集數"""
    room_id = data.get('room', 'default')
    movie = data.get('movie')
    episode = data.get('episode')
    
    room_state = get_room_state(room_id)
    room_state.update({
        'current_movie': movie,
        'current_episode': episode,
        'is_playing': True,
        'current_time': 0
    })
    
    # 只廣播給該房間的客戶端
    socketio.emit('play_episode', {
        'movie': movie,
        'episode': episode,
        'file_path': data.get('file_path')
    }, room=room_id)
    
    socketio.emit('state_update', room_state, room=room_id)
    socketio.emit('rooms_update')  # 更新房間列表
    
    print(f'房間 {room_id} 播放: {movie} - {episode}')

@socketio.on('play_pause')
def handle_play_pause(data):
    """播放/暫停控制"""
    room_id = data.get('room', 'default')
    is_playing = data.get('is_playing', False)
    
    room_state = get_room_state(room_id)
    room_state['is_playing'] = is_playing
    
    socketio.emit('play_pause', {'is_playing': is_playing}, room=room_id)
    socketio.emit('state_update', room_state, room=room_id)
    socketio.emit('rooms_update')  # 更新房間列表
    
    print(f'房間 {room_id} 播放狀態: {"播放" if is_playing else "暫停"}')

@socketio.on('seek')
def handle_seek(data):
    """快進快退控制"""
    room_id = data.get('room', 'default')
    seek_time = data.get('time', 0)
    
    room_state = get_room_state(room_id)
    room_state['current_time'] = seek_time
    
    socketio.emit('seek', {'time': seek_time}, room=room_id)
    socketio.emit('state_update', room_state, room=room_id)
    
    print(f'房間 {room_id} 跳轉到: {seek_time}秒')

@socketio.on('volume')
def handle_volume(data):
    """音量控制"""
    room_id = data.get('room', 'default')
    volume = data.get('volume', 1.0)
    
    room_state = get_room_state(room_id)
    room_state['volume'] = volume
    
    socketio.emit('volume', {'volume': volume}, room=room_id)
    socketio.emit('state_update', room_state, room=room_id)
    
    print(f'房間 {room_id} 音量: {volume * 100}%')

@socketio.on('fullscreen')
def handle_fullscreen(data):
    """全螢幕控制"""
    room_id = data.get('room', 'default')
    
    socketio.emit('fullscreen', data, room=room_id)
    print(f'房間 {room_id} 切換全螢幕模式')

@socketio.on('time_update')
def handle_time_update(data):
    """時間更新（來自播放器）"""
    room_id = data.get('room', 'default')
    current_time = data.get('time', 0)
    
    room_state = get_room_state(room_id)
    room_state['current_time'] = current_time
    # 只更新狀態，不廣播避免循環

@socketio.on('video_ended')
def handle_video_ended(data):
    """處理影片播放結束事件"""
    room_id = data.get('room', 'default')
    
    room_state = get_room_state(room_id)
    room_state['is_playing'] = False
    
    # 廣播播放結束事件給該房間的控制台
    socketio.emit('video_ended', {
        'room': room_id,
        'movie': room_state['current_movie'],
        'episode': room_state['current_episode'],
        'timestamp': data.get('timestamp', time.time())
    }, room=room_id)
    
    # 更新房間狀態
    socketio.emit('state_update', room_state, room=room_id)
    socketio.emit('rooms_update')  # 更新房間列表
    
    print(f'房間 {room_id} 影片播放結束: {room_state["current_movie"]} - {room_state["current_episode"]}')

if __name__ == '__main__':
    print("="*50)
    print("    電影播放伺服器啟動中...")
    print("="*50)
    print(f"    主頁: http://localhost:{PORT}")
    print(f"    播放器: http://localhost:{PORT}/player")
    print(f"    控制台: http://localhost:{PORT}/control")
    print("="*50)
    print(f"    影片目錄: {os.path.abspath(DATA_DIR)}")
    print("    請將影片按以下結構放置:")
    print("    ./data/片名/縮圖.jpg")
    print("    ./data/片名/集數.mp4")
    print("    ./data/片名/集數.jpg")
    print("="*50)
    
    # 建立範例目錄結構
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        print(f"    已建立目錄: {DATA_DIR}")
    
    try:
        socketio.run(app, host='0.0.0.0', port=PORT, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        print("\n伺服器已停止")
