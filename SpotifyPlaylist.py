import spotipy
import pandas as pd
import numpy as np
import requests
from spotipy import oauth2
import re

SPOTIPY_CLIENT_ID = ''
SPOTIPY_CLIENT_SECRET = ''
SCOPE = ('user-read-recently-played,user-library-read,user-read-currently-playing,playlist-read-private,playlist-modify-private,playlist-modify-public,user-read-email,user-modify-playback-state,user-read-private,user-read-playback-state')
# Using port like 8080 allows spotify to auto auth
SPOTIPY_REDIRECT_URI = 'http://localhost:8080/'
sp_oauth = oauth2.SpotifyOAuth( SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET,SPOTIPY_REDIRECT_URI,scope=SCOPE )

#click "Accept" in your browser when the auth window pops up
code = sp_oauth.get_auth_response(open_browser=True)
token = sp_oauth.get_access_token(code)
refresh_token = token['refresh_token']
sp = spotipy.Spotify(auth=token['access_token'])
username = sp.current_user()['id']

#Making a playlist
pl_name = 'MyEndlessPlaylist'
result = sp.user_playlist_create(username, name=pl_name)
pl_id = result['id']

#ID for the public spotify playlist we're getting all the albums from 
top_album_pl = '70n5zfYco8wG777Ua2LlNv'

#top_albums is list we'll use to make the top albums playlist
top_albums = []
offset = 0
while True:
    response = sp.playlist_items(top_album_pl, offset=offset)
    
    if len(response['items']) == 0:
        break
    top_albums +=response['items']
    offset = offset + len(response['items'])

#Here we make a DataFrame of all the top albums by looping through that list of response of dictionaries
album_df = []
for album in top_albums:
    
    track = album['track']['name']
    artist = album['track']['artists'][0]['name']
    album_name = album['track']['album']['name']
    track_id = album['track']['id']
    album_id = album['track']['album']['id']
    album_df.append([track,artist,album_name, track_id,album_id])
album_df = pd.DataFrame(album_df, columns =['track','artist','album','track_id','album_id'])

#random seed so others can get the same album order as me
np.random.seed(10)

#make a DataFrame of all albums and add a random number between 0-1 "rand_key" for each album
all_albums = album_df.drop_duplicates('album_id').album_id
all_albums = pd.DataFrame(all_albums).reset_index(drop=True)
all_albums['rand_key'] = np.random.rand(len(all_albums))

#merge the albums DataFrame back with the full top albums DataFrame
album_df = pd.merge(album_df, all_albums, how='inner', on='album_id')

#sort by the rand_key (and by index so the songs within albums stay in order)
album_df['idx'] = album_df.index
album_df = album_df.sort_values(['rand_key','idx']).reset_index(drop=True)

#run the code below to exclude one-track albums
album_df_piv = pd.pivot_table(album_df, index='album_id',values='track_id',aggfunc='count')
album_df_piv.columns = ['num_tracks']
album_df = pd.merge(album_df, album_df_piv, how='left',left_on='album_id',right_index=True)
album_df = album_df[album_df.num_tracks>1].reset_index(drop=True)

album_df['idx'] = album_df.index

#do some data cleaning (getting rid of quotes, backslashes) so it will play nice 
album_df.loc[(album_df['track'].str.contains('"')),'track'] = album_df.track.str.replace('"','')
album_df.loc[(album_df['artist'].str.contains('"')),'artist'] = album_df.artist.str.replace('"','')
album_df.loc[(album_df['album'].str.contains('"')),'album'] = album_df.album.str.replace('"','')
album_df.loc[(album_df['track'].str.contains(r"\\")),'track'] = album_df.track.str.replace('\\','')

#copy this album df to your clipboard to paste into google sheets or elsewhere.
album_df.to_clipboard(index=False)

#initialize playlist of length 30
pl_length = 100
last_tracks_added = album_df.loc[0:pl_length-1]
tracks_to_add = last_tracks_added.track_id.tolist()
sp.playlist_add_items(pl_id, tracks_to_add )

#make lists of playlist track id's and names to check against your recently played tracks
this_pl = sp.playlist_items(pl_id)['items']
this_pl_ids = [track['track']['id'] for track in this_pl]

#we'll use this list of track+artist names to find tracks that got added to our playlist with a different track_id (which sometimes happens)
this_pl_names = [re.sub('[^0-9a-zA-Z]+', '',track['track']['name']+track['track']['artists'][0]['name']) for track in this_pl]

#make a "to_delete" list of the index and URI of songs you in your playlist that you just listened to
to_delete = []
recents = sp.current_user_recently_played(50)['items']
for track in recents:
    context = track['context']
    if context and 'playlist' in context['uri']:
        this_pl_id = context['uri'].split('playlist:')[1]
        name_artist = re.sub('[^0-9a-zA-Z]+', '',track['track']['name']+track['track']['artists'][0]['name'])
        if track['track']['id'] in this_pl_ids and this_pl_id == pl_id :
            idx = this_pl_ids.index(track['track']['id'])
            uri = track['track']['uri']
            to_delete.append([idx,uri])
        #including a second if statement in case that track id isn't in the playlist but that track+artist is.
        elif this_pl_id == pl_id  and name_artist in this_pl_names:
            idx = this_pl_names.index(name_artist)
            uri = 'spotify:track:' + this_pl_ids[idx]
            to_delete.append([idx,uri]) 

#if there's no songs to delete then there's no updates to make
if len(to_delete) > 0:

    #use that list to create a list of track dictionaries (which have track uri and position in the playlist)
    tracks = [{'uri': track[1], 'positions': [track[0]]} for track in to_delete]

    #use that list of track dictionaries and delete them from your playlist
    sp.user_playlist_remove_specific_occurrences_of_tracks(username,pl_id,tracks)


    #make a 'tracks_to_add' DataFrame that is the same length as the "to_delete" list
    to_add = len(to_delete)
    last_index = last_tracks_added['idx'].astype(int).max()
    tracks_to_add = album_df.loc[last_index+1:last_index+to_add]

		#to make it truly "endless" start adding the first tracks again once you reach the end
    if (last_index+to_add) >= len(album_df):
        tracks_to_add = pd.concat([tracks_to_add, album_df.loc[0:(last_index+to_add)%len(album_df)]],axis=0)

    #add those songs to your playlist 
    sp.playlist_add_items(pl_id,tracks_to_add.track_id.tolist())
