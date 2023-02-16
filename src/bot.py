# -*- coding: utf-8 -*-

"""
Copyright (c) 2019 Valentin B.
A simple music bot written in discord.py using youtube-dl.
Though it's a simple example, music bots are complex and require much time and knowledge until they work perfectly.
Use this as an example or a base for your own bot and extend it as you want. If there are any bugs, please let me know.
Requirements:
Python 3.5+
pip install -U discord.py pynacl youtube-dl
You also need FFmpeg in your PATH environment variable or the FFmpeg.exe binary in your bot's directory on Windows.
"""

import asyncio
import math
import os

import discord
import yaml
from async_timeout import timeout
from discord.ext import commands
from dotenv import load_dotenv
from yaml import Loader

from media import Playlist, Song, SongQueue
from ytdl import YTDLError, YTDLSource

load_dotenv()


class VoiceError(Exception):
    pass


class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            try:
                if not self.loop:
                    # Try to get the next song within 3 minutes.
                    # If no song will be added to the queue in time,
                    # the player will disconnect due to performance
                    # reasons.
                    try:
                        async with timeout(180):  # 3 minutes
                            self.current = await self.songs.get()
                    except asyncio.TimeoutError:
                        self.bot.loop.create_task(self.stop())
                        print("Player timed out.")
                        continue

                self.current.source.volume = self._volume
                self.voice.play(self.current.source, after=self.play_next_song)
                await self.current.source.channel.send(
                    embed=self.current.create_embed()
                )
            except Exception as e:
                await self._ctx.send("An error occurred while playing audio.")
                print(e)

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage(
                "This command can't be used in DM channels."
            )

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        await ctx.send("An error occurred: {}".format(str(error)))

    @commands.command(name="join", invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name="leave", aliases=["disconnect"])
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send("Not connected to any voice channel.")

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name="volume")
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send("Nothing being played at the moment.")

        if 0 > volume > 100:
            return await ctx.send("Volume must be between 0 and 100")

        ctx.voice_state.volume = volume / 100
        await ctx.send("Volume of the player set to {}%".format(volume))

    @commands.command(name="now", aliases=["current", "playing"])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""

        await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(name="pause")
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction("⏯")

    @commands.command(name="resume")
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction("⏯")

    @commands.command(name="stop")
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction("⏹")

    @commands.command(name="skip")
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send("Not playing any music right now...")

        # voter = ctx.message.author
        # if voter == ctx.voice_state.current.requester:
        await ctx.message.add_reaction("⏭")
        ctx.voice_state.skip()

        # elif voter.id not in ctx.voice_state.skip_votes:
        #     ctx.voice_state.skip_votes.add(voter.id)
        #     total_votes = len(ctx.voice_state.skip_votes)
        #
        #     if total_votes >= 3:
        #         await ctx.message.add_reaction("⏭")
        #         ctx.voice_state.skip()
        #     else:
        #         await ctx.send(
        #             "Skip vote added, currently at **{}/3**".format(total_votes)
        #         )
        #
        # else:
        #     await ctx.send("You have already voted to skip this song.")

    @commands.command(name="queue")
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.
        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("Empty queue.")

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ""
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += "`{0}.` [**{1.source.title}**]({1.source.url})\n".format(
                i + 1, song
            )

        embed = discord.Embed(
            description="**{} tracks:**\n\n{}".format(len(ctx.voice_state.songs), queue)
        ).set_footer(text="Viewing page {}/{}".format(page, pages))
        await ctx.send(embed=embed)

    @commands.command(name="shuffle")
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("Empty queue.")

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction("✅")

    @commands.command(name="dequeue")
    async def _remove(self, ctx: commands.Context, index: int):
        """
        Removes a song from the queue at a given index.
        !dequeue <index>
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("Empty queue.")

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction("✅")

    @commands.command(name="loop")
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song. <Broken>
        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send("Nothing being played at the moment.")

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction("✅")

    @commands.command(name="play")
    async def _play(self, ctx: commands.Context, *, search: str):
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send(
                    "An error occurred while processing this request: {}".format(str(e))
                )
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)
                await ctx.send("Enqueued {}".format(str(source)))

    @commands.command(name="new")
    async def _new_playlist(self, ctx: commands.Context, *, name: str):
        """
        Creates a new playlist with the given name.
        !new <playlist name>
        """

        playlist_file = "playlists.yaml"
        if not os.path.exists(playlist_file):
            with open(playlist_file, "w") as f:
                f.write("playlists: {}")

        with open(playlist_file, "r") as f:
            playlists = yaml.load(f, Loader=Loader)

        if name in playlists["playlists"]:
            return await ctx.send("Playlist already exists.")

        playlists["playlists"][name] = Playlist(name)
        with open(playlist_file, "w") as f:
            yaml.dump(playlists, f)

        await ctx.message.add_reaction("✅")
        await ctx.send("Playlist created.")

    @commands.command(name="add")
    async def _add_to_playlist(self, ctx: commands.Context, name: str, search: str):
        """
        Adds a song to a playlist.
        !add <playlist name> <song name/url>
        """

        playlist_file = "playlists.yaml"
        if not os.path.exists(playlist_file):
            with open(playlist_file, "w") as f:
                f.write("playlists: {}")

        with open(playlist_file, "r") as f:
            playlists = yaml.load(f, Loader=Loader)

        if name not in playlists["playlists"]:
            return await ctx.send("Playlist does not exist.")

        playlists["playlists"][name].add_song(search)

        with open(playlist_file, "w") as f:
            yaml.dump(playlists, f)

        await ctx.message.add_reaction("✅")
        await ctx.send("Song added to playlist.")

    @commands.command(name="remove")
    async def _remove_from_playlist(
        self, ctx: commands.Context, name: str, search: str
    ):
        """
        Removes a song from a playlist.
        !remove <playlist name> <song name/url>
        """

        playlist_file = "playlists.yaml"
        if not os.path.exists(playlist_file):
            with open(playlist_file, "w") as f:
                f.write("playlists: {}")

        with open(playlist_file, "r") as f:
            playlists = yaml.load(f, Loader=Loader)

        if name not in playlists["playlists"]:
            return await ctx.send("Playlist does not exist.")

        playlists["playlists"][name].remove_song(search)

        with open(playlist_file, "w") as f:
            yaml.dump(playlists, f)

        await ctx.message.add_reaction("✅")
        await ctx.send("Song removed from playlist.")

    @commands.command(name="playpl")
    async def _play_playlist(self, ctx: commands.Context, *, name: str):
        """
        Plays all songs in a playlist. Clears the current queue.
        !playpl <playlist name>
        """

        if ctx.voice_state.voice:
            ctx.voice_state.songs.clear()

            if ctx.voice_state.is_playing:
                ctx.voice_state.voice.stop()

        playlist_file = "playlists.yaml"
        if not os.path.exists(playlist_file):
            with open(playlist_file, "w") as f:
                f.write("playlists: {}")

        with open(playlist_file, "r") as f:
            playlists = yaml.load(f, Loader=Loader)

        if name not in playlists["playlists"]:
            return await ctx.send("Playlist does not exist.")

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        for url in playlists["playlists"][name].songs:
            async with ctx.typing():
                try:
                    source = await YTDLSource.create_source(
                        ctx, url, loop=self.bot.loop
                    )
                except YTDLError as e:
                    await ctx.send(
                        "An error occurred while processing this request: {}".format(
                            str(e)
                        )
                    )
                else:
                    song = Song(source)

                    await ctx.voice_state.songs.put(song)
                    await ctx.send("Enqueued {}".format(str(source)))

        await ctx.message.add_reaction("✅")
        await ctx.send("Playlist added to queue.")

    @commands.command(name="delete")
    async def _delete_playlist(self, ctx: commands.Context, *, name: str):
        """
        Deletes a playlist.
        !delete <playlist name>
        """

        playlist_file = "playlists.yaml"
        if not os.path.exists(playlist_file):
            with open(playlist_file, "w") as f:
                f.write("playlists: {}")

        with open(playlist_file, "r") as f:
            playlists = yaml.load(f, Loader=Loader)

        if name not in playlists["playlists"]:
            return await ctx.send("Playlist does not exist.")

        del playlists["playlists"][name]

        with open(playlist_file, "w") as f:
            yaml.dump(playlists, f)

        await ctx.message.add_reaction("✅")
        await ctx.send("Playlist deleted.")

    @commands.command(name="list")
    async def _list_playlists(self, ctx: commands.Context):
        """
        Lists all playlists.
        """

        playlist_file = "playlists.yaml"
        if not os.path.exists(playlist_file):
            with open(playlist_file, "w") as f:
                f.write("playlists: {}")

        with open(playlist_file, "r") as f:
            playlists = yaml.load(f, Loader=Loader)

        if not playlists["playlists"]:
            return await ctx.send("No playlists exist.")

        await ctx.send("Playlists: {}".format(", ".join(playlists["playlists"].keys())))

    @commands.command(name="listpl")
    async def _list_playlist(self, ctx: commands.Context, *, name: str):
        """
        List the songs in a playlist.
        """

        playlist_file = "playlists.yaml"
        if not os.path.exists(playlist_file):
            with open(playlist_file, "w") as f:
                f.write("playlists: {}")

        with open(playlist_file, "r") as f:
            playlists = yaml.load(f, Loader=Loader)

        if name not in playlists["playlists"]:
            return await ctx.send("Playlist does not exist.")

        pl = playlists["playlists"][name]

        with ctx.typing():
            songs = ""
            for i, song in enumerate(pl.songs):
                try:
                    source = await YTDLSource.create_source(
                        ctx, song, loop=self.bot.loop
                    )
                except YTDLError as e:
                    await ctx.send(
                        "An error occurred while processing this request: {}".format(
                            str(e)
                        )
                    )
                else:
                    title = source.title
                    url = source.url

                    songs += "{}. [{}]({})\n".format(i + 1, title, url)

        embed = discord.Embed(
            title="Playlist: {}".format(name),
            description=songs,
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError("You are not connected to any voice channel.")

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError("Bot is already in a voice channel.")


bot = commands.Bot(command_prefix="!", description="Yet another music bot.")
bot.add_cog(Music(bot))


@bot.event
async def on_ready():
    print("Logged in as:\n{0.user.name}\n{0.user.id}".format(bot))


DISCORD_TOKEN = os.getenv("discord_token")
bot.run(DISCORD_TOKEN)
