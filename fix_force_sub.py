import sqlite3, os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot1.db")
print("DB found at:", db_path)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Show current channels
c.execute("SELECT id, channel_url, description, enabled FROM force_sub_channels")
print("\nCurrent force-sub channels:")
for row in c.fetchall():
    print(row)

# Delete the A_ToolsX channel
c.execute("DELETE FROM force_sub_channels WHERE channel_url LIKE '%A_ToolsX%'")
conn.commit()
print(f"\n✅ Deleted {c.rowcount} channel(s).")

# Disable force-sub globally
c.execute("UPDATE bot_settings SET value = '0' WHERE key = 'force_sub_enabled'")
c.execute("DELETE FROM bot_settings WHERE key = 'force_sub_channel'")
conn.commit()

# Show remaining
c.execute("SELECT id, channel_url, description, enabled FROM force_sub_channels")
print("\nRemaining channels:")
for row in c.fetchall():
    print(row)

conn.close()
print("\n🎉 Done. Restart your bot.")
