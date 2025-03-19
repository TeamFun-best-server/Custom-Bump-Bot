import discord
import aiohttp
from discord.ext import commands, tasks
from discord import Interaction, app_commands
import yaml
import os
import asyncio
import random
import dotenv
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Optional


# Bot instellingen
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
OWNER_IDS = {1198268147027955763, 9876543210}  # Jouw ID's hier
BUMP_LIMIT = 100  # Maximaal aantal servers waar een bump naartoe gaat

# Mappen en bestanden automatisch aanmaken
DATA_FOLDER = "servers"
BLOCKLIST_FILE = "blocked-servers.yml"
PREMIUM_FILE = "premium-servers.yml"
PREMIUM_DATA = "premium-servers.yml"

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

for folder in [DATA_FOLDER]:
    os.makedirs(folder, exist_ok=True)
for file in [BLOCKLIST_FILE, PREMIUM_FILE]:
    if not os.path.exists(file):
        with open(file, "w") as f:
            yaml.dump({}, f)

# Laad YAML-bestanden
def load_yaml(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}
        
def get_bump_channel(guild_id):
    data = load_yaml("bump.yml")
    return data.get(str(guild_id), {}).get("channel", None)


# Check of een server geblokkeerd is
def is_blacklisted(server_id):
    blocked_servers = load_yaml(BLOCKLIST_FILE)
    return str(server_id) in blocked_servers

# ✅ Functie om YAML op te slaan (nu zonder fout)
def save_yaml(file_path, data):
    directory = os.path.dirname(file_path)

    # Zorg dat de map correct wordt aangemaakt
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False)

# 📂 Functie om het serverbestandspad te krijgen
def get_server_file(guild_id, filename):
    return f"servers/{guild_id}/{filename}.yml"

def load_premium_data():
    """ Laadt de premium server data uit premium-servers.yml. """
    if not os.path.exists(PREMIUM_FILE):
        return {}  # Als het bestand niet bestaat, geef een lege dict terug

    with open(PREMIUM_FILE, "r", encoding="utf-8") as file:
        try:
            return yaml.safe_load(file) or {}  # Zorg dat we een dict terugkrijgen
        except yaml.YAMLError:
            return {}  # Voorkom crashes als het YAML-bestand corrupt is

def save_premium_data(data):
    """ Slaat de premium server data op in premium-servers.yml. """
    with open(PREMIUM_FILE, "w", encoding="utf-8") as file:
        yaml.dump(data, file, default_flow_style=False, allow_unicode=True)


class AdModal(discord.ui.Modal, title="📄 Enter Your Advertisement"):
    advertisement = discord.ui.TextInput(
        label="Your Advertisement",
        style=discord.TextStyle.paragraph,
        placeholder="Type your advertisement here...",
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        self.ad_content = self.advertisement.value  # ✅ Opslaan als string
        self.stop()


class AdInputView(discord.ui.View):
    def __init__(self, interaction):
        super().__init__(timeout=60)
        self.interaction = interaction
        self.selected_ad = None

        self.select_ad_button = discord.ui.Button(label="📄 Enter your advertisement", style=discord.ButtonStyle.primary)
        self.select_ad_button.callback = self.enter_new_ad
        self.add_item(self.select_ad_button)

    async def enter_new_ad(self, interaction: discord.Interaction):
        modal = AdModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.selected_ad = modal.ad_content  # ✅ Gebruik opgeslagen waarde
        self.stop()


class ChannelSelectView(discord.ui.View):
    def __init__(self, interaction):
        super().__init__(timeout=60)
        self.interaction = interaction
        self.selected_channel = None

        self.channel_select = discord.ui.Select(
            placeholder="🗂 Select a bump channel...",
            options=[
                discord.SelectOption(label=channel.name, value=str(channel.id))
                for channel in interaction.guild.text_channels[:25]
            ]
        )
        self.channel_select.callback = self.select_channel
        self.add_item(self.channel_select)

        self.confirm_button = discord.ui.Button(label="Use this channel", style=discord.ButtonStyle.green)
        self.confirm_button.callback = self.use_current_channel
        self.add_item(self.confirm_button)

    async def select_channel(self, interaction: Interaction):
        self.selected_channel = int(self.channel_select.values[0])
        await interaction.response.send_message(f"✅ Selected <#{self.selected_channel}> as bump channel.", ephemeral=True)
        self.stop()

    async def use_current_channel(self, interaction: Interaction):
        self.selected_channel = self.interaction.channel.id
        await interaction.response.send_message(f"✅ Set this channel (<#{self.selected_channel}>) as bump channel.", ephemeral=True)
        self.stop()


@bot.tree.command(name="setup", description="Setup bump system for this server.")
async def setup(interaction: Interaction):
    guild_id = interaction.guild.id
    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

    # 1️⃣ Controleer of de server op de blacklist staat
    blocked_servers = load_yaml("blocked-servers.yml") or {"blacklisted": []}
    if guild_id in blocked_servers["blacklisted"]:
        return await interaction.response.send_message("⛔️ This server is blacklisted. Please contact the support team with '/support'!", ephemeral=True)
    
        # 🔒 Controleer of de gebruiker "Manage Server" permissie heeft
    # Controleer of de gebruiker permissies heeft
    if not interaction.user.guild_permissions.manage_guild and interaction.user.id not in get_managers(guild.id):
        return await interaction.response.send_message("❌ You need **Manage Server** permission or need to be added as Manager in this server to use this command.", ephemeral=True)


    # 2️⃣ Selecteer een bump channel
    channel_view = ChannelSelectView(interaction)
    await interaction.response.send_message("📢 **Select a bump channel:**", view=channel_view, ephemeral=True)
    await channel_view.wait()

    if not channel_view.selected_channel:
        return await interaction.followup.send("❌ Setup cancelled (no channel selected).", ephemeral=True)

    bump_channel = interaction.guild.get_channel(channel_view.selected_channel)

    # 3️⃣ Controleer of de bot permissies heeft om daar berichten te sturen
    if not bump_channel.permissions_for(interaction.guild.me).send_messages:
        return await interaction.followup.send(f"❌ I don't have permission to send messages in <#{bump_channel.id}>. In order to set the server up, give me permission to talk in <#{bump_channel.id}>", ephemeral=True)

    # 4️⃣ Opslaan van bump channel
    save_yaml(get_server_file(guild_id, "bumps"), {"channel": bump_channel.id})

    # 5️⃣ Vraag om advertentie met knop
    ad_view = AdInputView(interaction)
    await interaction.followup.send("📝 **Click below to enter your advertisement:**", view=ad_view, ephemeral=True)
    await ad_view.wait()

    if not ad_view.selected_ad:
        return await interaction.followup.send("❌ Setup cancelled (no advertisement provided).", ephemeral=True)

    # 6️⃣ Opslaan van advertentie
    save_yaml(get_server_file(guild_id, "ad"), {"message": ad_view.selected_ad})

    await interaction.followup.send("✅ Setup completed successfully!", ephemeral=True)
bump_cooldowns = {}

@bot.tree.command(name="bump", description="Send your advertisement to other servers.")
async def bump(interaction: Interaction):
    await interaction.response.defer()
    guild = interaction.guild
    guild_id = guild.id

    # Check of de server is geblacklist
    if is_blacklisted(guild_id):
        return await interaction.response.send_message("⛔️ This server is blacklisted. Please contact the support team with '/support'.", ephemeral=True)

    # Cooldown check
    now = datetime.utcnow()
    cooldown_time = timedelta(minutes=60 if not is_premium(guild_id) else 45)

    if guild_id in bump_cooldowns and bump_cooldowns[guild_id] > now:
        remaining = bump_cooldowns[guild_id] - now
        return await interaction.response.send_message(
            f"⏳ You must wait {remaining.seconds // 60} minutes before bumping again. Want faster cooldowns? Purchage premium", ephemeral=True
        )

    # Laad advertentie en bump-kanaal
    ad_data = load_yaml(get_server_file(guild_id, "ad"))
    bump_data = load_yaml(get_server_file(guild_id, "bumps"))

    ad_message = ad_data.get("message")
    bump_channel_id = bump_data.get("channel")

    # Controleer of het bump-kanaal geldig is
    if not bump_channel_id:
        return await interaction.response.send_message(
            "❌ No bump channel is set up. Use `/setup` first.", ephemeral=True
        )

    channel = guild.get_channel(bump_channel_id)

    if not channel:
        return await interaction.response.send_message(
            "❌ I didn't found the bump channel.. Please use `/setup` again.", ephemeral=True
        )

    if not channel.permissions_for(guild.me).send_messages:
        return await interaction.response.send_message(
            "❌ I don't have permission to send messages in the bump channel! In order to use the /bump command, please give me permission to talk in your bump channel.", ephemeral=True
        )

    # Selecteer servers voor bump
    all_servers = [g for g in bot.guilds if g.id != guild_id]
    random.shuffle(all_servers)  # Schud de lijst om willekeurig te kiezen
    target_servers = all_servers[:random.randint(50, 100)]

    sent_count = 0
    for i, target_guild in enumerate(target_servers):
        target_bump_data = load_yaml(get_server_file(target_guild.id, "bumps"))
        target_channel_id = target_bump_data.get("channel")

        if target_channel_id:
            target_channel = bot.get_channel(int(target_channel_id))
            if target_channel:
                try:
                    await target_channel.send(ad_message)
                    sent_count += 1
                except discord.Forbidden:
                    print(f"❌ Cannot send message in {target_guild.name} (missing permissions)")

        # Voorkom ratelimiting: wacht 10 seconden per 20 servers
        if (i + 1) % 20 == 0:
            await asyncio.sleep(10)

    # Update cooldown
    bump_cooldowns[guild_id] = now + cooldown_time

    # Update totaal aantal bumps
    total_bumps_data = load_yaml(get_server_file(guild_id, "total-bumps"))
    total_bumps = total_bumps_data.get("count", 0) + 1
    save_yaml(get_server_file(guild_id, "total-bumps"), {"count": total_bumps})

    # Embed bevestiging
    embed = discord.Embed(
        title="✅ Successful Bump!",
        description=f"Thanks for using **XtremeBump** as your bump bot!\nYour advertisement was shared with **{sent_count} servers**.\nThis server has a total of **{total_bumps} bumps**!\n\nDid you know, you can get usefull commands by DMing me '!help'!",
        color=discord.Color.green()
    )
    embed.set_footer(text="XtremeBump. Get Discord members fast and easily!")

    try:
        await interaction.followup.send(embed=embed)
    except discord.errors.NotFound:
        await interaction.followup.send(embed=embed)


# ✅ Helper functie om de managers op te slaan
def get_managers(server_id):
    file_path = f"servers/{server_id}/special-managers.yml"
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data.get("managers", [])

def save_managers(server_id, managers):
    file_path = f"servers/{server_id}/special-managers.yml"
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        yaml.dump({"managers": managers}, f)
        
# ✅ /addmanager <user>
@bot.tree.command(name="addmanager", description="Add a manager for this server")
async def addmanager(interaction: discord.Interaction, user: discord.User):
    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

    if not (interaction.user.guild_permissions.manage_guild or interaction.user.id in get_managers(guild.id)):
        return await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)


    managers = get_managers(guild.id)

    if user.id in managers:
        return await interaction.response.send_message(f"❌ {user.mention} is already a manager.", ephemeral=True)

    managers.append(user.id)
    save_managers(guild.id, managers)
    
    await interaction.response.send_message(f"✅ {user.mention} has been added as a manager!", ephemeral=False)

# ✅ /removemanager <user>
@bot.tree.command(name="removemanager", description="Remove a manager from this server")
async def removemanager(interaction: discord.Interaction, user: discord.User):
    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

    # Controleer of de gebruiker permissies heeft
    if not interaction.user.guild_permissions.manage_guild and interaction.user.id not in get_managers(guild.id):
        return await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)

    managers = get_managers(guild.id)

    if user.id not in managers:
        return await interaction.response.send_message(f"❌ {user.mention} is not a manager.", ephemeral=True)

    managers.remove(user.id)
    save_managers(guild.id, managers)

    await interaction.response.send_message(f"✅ {user.mention} has been removed as a manager!", ephemeral=False)
    
# ✅ `/leaderboard` - Top 10 servers met meeste bumps
@bot.tree.command(name="leaderboard", description="Show the top 10 servers with the most bumps.")
async def leaderboard(interaction: Interaction):
    if is_blacklisted(interaction.guild.id):
        return await interaction.response.send_message("⛔️ This server is blacklisted. Please contact our support team with '/support'.", ephemeral=True)

    servers = {s: load_yaml(get_server_file(s, "total-bumps")).get("count", 0) for s in os.listdir("servers") if s.isdigit()}
    top_servers = sorted(servers.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(title="📊 Bump Leaderboard", color=discord.Color.blue())
    for i, (server_id, count) in enumerate(top_servers, 1):
        embed.add_field(name=f"#{i}", value=f"Server ID: {server_id} - {count} bumps", inline=False)

    await interaction.response.send_message(embed=embed)

# ✅ `/blacklist` - Blokkeert een server in het systeem
@bot.tree.command(name="blacklist", description="Blacklist a server from using the bump system.")
async def blacklist(interaction: Interaction, server_id: str):
    allowed_users = [1198268147027955763, 9876543210]  # Jouw ID en die van een andere dev

    if interaction.user.id not in allowed_users:
        return await interaction.response.send_message("⛔️ You do not have permission to use this command.", ephemeral=True)

    if not server_id.isdigit():
        return await interaction.response.send_message("❌ Invalid server ID.", ephemeral=True)

    guild_id = int(server_id)
    file_path = "blocked-servers.yml"

    # Laad de blacklist en update het bestand
    blocked = load_yaml(file_path) or {"blacklisted": []}
    if guild_id not in blocked["blacklisted"]:
        blocked["blacklisted"].append(guild_id)
        save_yaml(file_path, blocked)
        await interaction.response.send_message(f"✅ Server **{guild_id}** has been blacklisted.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ This server is already blacklisted.", ephemeral=True)

# ✅ `/removeblacklist` - Haalt een server van de blacklist
@bot.tree.command(name="removeblacklist", description="Remove a server from the blacklist.")
async def remove_blacklist(interaction: Interaction, server_id: str):
    allowed_users = [1198268147027955763, 9876543210]  # Jouw ID en die van een andere dev

    if interaction.user.id not in allowed_users:
        return await interaction.response.send_message("⛔️ You do not have permission to use this command.", ephemeral=True)

    if not server_id.isdigit():
        return await interaction.response.send_message("❌ Invalid server ID.", ephemeral=True)

    guild_id = int(server_id)
    file_path = "blocked-servers.yml"

    # Laad blacklist en verwijder de server
    blocked = load_yaml(file_path) or {"blacklisted": []}
    if guild_id in blocked["blacklisted"]:
        blocked["blacklisted"].remove(guild_id)
        save_yaml(file_path, blocked)
        await interaction.response.send_message(f"✅ Server **{guild_id}** has been removed from the blacklist.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ This server is not blacklisted.", ephemeral=True)

# ✅ /premium met embed
@bot.tree.command(name="premium", description="Get premium")
async def premium(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💎 Get Premium!",
        description="Unlock premium benefits for your server!\n[Join our support server](https://discord.gg/eDMGawH7HH)",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

# ✅ /support met embed
@bot.tree.command(name="support", description="Get the invite to our support server")
async def support(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🆘 Support Server",
        description="Need help? Join our support server:\n[Click here](https://discord.gg/eDMGawH7HH)",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="grand-premium", description="Grant a server premium status for a set number of days.")
async def set_premium(interaction: Interaction, server_id: str, days: int):
    allowed_users = [1198268147027955763, 9876543210]  # Voeg jouw ID's toe

    if interaction.user.id not in allowed_users:
        return await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)

    if not server_id.isdigit():
        return await interaction.response.send_message("❌ Invalid server ID.", ephemeral=True)

    guild_id = str(server_id)  # Opslaan als string voor consistentie in YAML
    expiry_date = datetime.utcnow() + timedelta(days=days)

    premium_data = load_premium_data()
    premium_data[guild_id] = {"expires": expiry_date.strftime("%Y-%m-%d %H:%M:%S")}
    save_premium_data(premium_data)

    await interaction.response.send_message(
        f"✅ Server **{guild_id}** is now premium until **{expiry_date} UTC**!", ephemeral=True
    )

def is_premium(guild_id):
    """ Checkt of een server premium is door de verloopdatum te controleren. """
    premium_data = load_premium_data()
    guild_info = premium_data.get(str(guild_id))

    if not guild_info or "expires" not in guild_info:
        return False  # Geen premium of geen vervaldatum

    expiry_str = guild_info["expires"]
    
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
        return expiry_date > datetime.utcnow()
    except ValueError:
        return False  # Ongeldige datumwaarde voorkomt een crash


# ✅ Vote links lijst (kan je later uitbreiden zonder code te wijzigen)
VOTE_LINKS = [
    {"name": "DiscordBotList", "url": "https://discordbotlist.com/servers/xtremebump-support/upvote"},
    # Voeg hier later extra links toe zoals:
    # {"name": "Top.gg", "url": "https://top.gg/bot/123456789/vote"},
]

@bot.tree.command(name="vote", description="Vote for us!")
async def vote(interaction: Interaction):
    embed = discord.Embed(
        title="🗳️ Vote for us!",
        description="Already, thanks for voting! Below are some links to vote for us and support the server.",
        color=discord.Color.blue(),
    )

    # ✅ Automatisch alle vote-links toevoegen aan de embed
    for link in VOTE_LINKS:
        embed.add_field(name=link["name"], value=f"[Click here to vote]({link['url']})", inline=False)

    await interaction.response.send_message(embed=embed)
    
# ✅ /get-id <server-invite>
@bot.tree.command(name="get-id", description="Get the server ID from an invite link (Staff only)")
@app_commands.describe(invite="The invite link to the server")
async def get_id(interaction: discord.Interaction, invite: str):
    # Controleer of de gebruiker staff is (pas de ID's aan)
    staff_users = [1198268147027955763, 9876543210]  # Voeg hier jouw staff ID's toe
    if interaction.user.id not in staff_users:
        return await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)

    # Verwijder 'discord.gg/' als dat er nog voor staat
    invite_code = invite.replace("https://discord.gg/", "").replace("discord.gg/", "")

    # API request om de server-ID te krijgen
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true") as resp:
            if resp.status == 200:
                data = await resp.json()
                server_name = data['guild']['name']
                server_id = data['guild']['id']

                embed = discord.Embed(
                    title="🔍 Server ID Found",
                    description=f"**Server Name:** {server_name}\n**Server ID:** `{server_id}`",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message("❌ Invalid or expired invite link.", ephemeral=True)

            
import random

@tasks.loop(minutes=90)  # Auto-bump elke 1,5 uur
async def auto_bump():
    premium_data = load_yaml("premium-servers.yml") or {}  # Laad premium servers
    auto_bump_data = load_yaml("auto-bump.yml") or {}  # Opslag van bump data

    premium_servers = list(premium_data.keys())  # Alle premium servers ophalen

    if not premium_servers:
        print("❌ Geen premium servers gevonden voor auto-bump.")
        return

    for guild_id in premium_servers:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue  # Bot zit niet meer in de server

        ad_data = load_yaml(get_server_file(guild.id, "ad"))
        ad_message = ad_data.get("message", "No advertisement set.")

        # Kies willekeurig **100 andere servers** om de ad in te sturen
        target_servers = random.sample(bot.guilds, min(100, len(bot.guilds)))

        for target_guild in target_servers:
            if str(target_guild.id) == str(guild.id):
                continue  # Niet bumpen in de eigen server

            bump_channel_id = load_yaml(get_server_file(target_guild.id, "bumps")).get("channel")
            if not bump_channel_id:
                continue

            bump_channel = target_guild.get_channel(int(bump_channel_id))
            if not bump_channel or not bump_channel.permissions_for(target_guild.me).send_messages:
                continue

            try:
                await bump_channel.send(ad_message)
                print(f"✅ Auto-bumped in {target_guild.name}")

                auto_bump_data[str(guild.id)] = {"last_bumped": datetime.now().isoformat()}
                save_yaml("auto-bump.yml", auto_bump_data)  # Opslaan in auto-bump.yml
            except Exception as e:
                print(f"❌ Failed to bump in {target_guild.name}: {e}")
                
                
@bot.tree.command(name="managerlist", description="List all server managers.")
async def managerlist(interaction: Interaction):
    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

    # Rollen met "Manage Server" permissie
    manager_roles = [role for role in guild.roles if role.permissions.manage_guild]
    manager_roles_mentions = [role.mention for role in manager_roles] if manager_roles else ["None"]

    # Individuele managers uit bestand
    managers_file = f"servers/{guild.id}/special-managers.yml"
    managers_data = load_yaml(managers_file) or {}
    manager_ids = managers_data.get("managers", [])
    
    # Converteer IDs naar @mentions
    manager_mentions = [guild.get_member(int(mid)).mention for mid in manager_ids if guild.get_member(int(mid))] if manager_ids else ["None"]

    # Embed maken
    embed = discord.Embed(title="📋 Server Managers", color=discord.Color.blue())
    embed.add_field(name="🔹 Roles with Manage Server", value="\n".join(manager_roles_mentions), inline=False)
    embed.add_field(name="🔸 Assigned Managers", value="\n".join(manager_mentions), inline=False)
    embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)

    await interaction.response.send_message(embed=embed)

@bot.event
async def on_message(message):
    if message.guild is None and message.author != bot.user:  # Alleen in DM's reageren
        if message.content.startswith("!suggest "):
            suggestion = message.content[len("!suggest "):].strip()
            if not suggestion:
                return await message.channel.send("❌ Please provide a valid suggestion.")

            # Embed voor de support server
            channel = bot.get_channel(1345363894146826241)  # ID van het suggestiekanaal
            if channel:
                embed = discord.Embed(title="New Suggestion", description=suggestion, color=discord.Color.blue())
                embed.set_footer(text=f"Suggested by {message.author} ({message.author.id})")
                await channel.send(embed=embed)

            # Embed als reactie naar de gebruiker
            reply_embed = discord.Embed(
                title="Suggestion Submitted!",
                description="Thank you for your suggestion! Your suggestion has been posted in our Support server. It can be found here: https://discord.gg/Zb2pmrdgET",
                color=discord.Color.green()
            )
            await message.channel.send(embed=reply_embed)

    await bot.process_commands(message)  # Andere commando’s blijven werken
    
@bot.tree.command(name="check-premium", description="Check if a server has premium status.")
async def check_premium(interaction: discord.Interaction, server_id: Optional[str] = None):
    if server_id is None:
        server_id = str(interaction.guild.id)  # Gebruik de huidige server als geen ID is opgegeven

    premium_servers = load_yaml("premium-servers.yml") or {}

    if server_id in premium_servers and premium_servers[server_id].get("premium", False):
        await interaction.response.send_message(f"✅ Server `{server_id}` has **Premium** status.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Server `{server_id}` does **not** have Premium status.", ephemeral=True)

@bot.tree.command(name="info-commands", description="Get info commands you can DM me with!")
async def info_commands(interaction: Interaction):
    embed = discord.Embed(title="📩 Info Commands", description="You can DM me with the following commands:", color=discord.Color.blue())
    embed.add_field(name="📨 `!suggest <suggestion>`", value="Send a suggestion to the developers!", inline=False)
    embed.add_field(name="💰 `!paidpromo`", value="Get info about hosting a paid promo in our support server.", inline=False)
    embed.add_field(name="❓ `!help`", value="This is the main help command.", inline=False)
    embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)

    await interaction.response.send_message(embed=embed)
    
@bot.event
async def on_message(message):
    if message.author.bot:
        return  # Negeer berichten van andere bots

    if isinstance(message.channel, discord.DMChannel):  # Controleer of het een DM is
        if message.content.lower() == "!paidpromo":
            embed = discord.Embed(title="💰 Paid Promotion", description="Want to promote your server with a paid promo? Here’s how it works!", color=discord.Color.gold())
            embed.add_field(name="📢 What is a paid promo?", value="A paid promo let you host a giveaway in the support server. The members first need to join your server before they can win. This makes your server growth go INSANE!", inline=False)
            embed.add_field(name="💵 Pricing & Details", value="Join our support server and create a support ticket for more info: [Support Server](https://discord.gg/eDMGawH7HH)", inline=False)
            await message.channel.send(embed=embed)
            print("!paidpromo is used.")

        elif message.content.lower() == "!help":
            embed = discord.Embed(title="❓ Help Command", description="Here are some useful commands you can use:", color=discord.Color.blue())
            embed.add_field(name="📩 `!suggest <suggestion>` *only works in DMs to me!*", value="Submit a suggestion to the developers.", inline=False)
            embed.add_field(name="💰 `!paidpromo` *only works in DMs to me!*", value="Get info about hosting a paid promo.", inline=False)
            embed.add_field(name="🔹 `/bump`", value="Manually bump your server.", inline=False)
            embed.add_field(name="🔸 `/setup`", value="Set up the bot for your server.", inline=False)
            embed.add_field(name="📈 `/leaderboard`", value="View the top 10 most active bump servers.")
            embed.add_field(name="🛠️ `/addmanager`, `/removemanager`", value="Add managers to your server that can run '/setup'.") 
            embed.set_footer(text="Need more help? Join our support server! /support.", icon_url=bot.user.display_avatar.url)
            await message.channel.send(embed=embed)
            print("!help us used.")

    await bot.process_commands(message)  # Zorg ervoor dat andere commands blijven werken


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"commands synced!")
    if not auto_bump.is_running():
        auto_bump.start()  # Start de auto-bump loop
    print(f"Auto-bump started!")
    print(f"Bot is logged in as XtremeBump.")

bot.run(TOKEN)
