# SMM – Kaunsi service me kaunsa link dena hai (v10)

Galat link = panel order CANCEL kar deta hai. Bot ab galat link order se PEHLE hi rok deta hai.
User bot me /linkguide bhej kar yeh list dekh sakta hai.

| Service | Link | Example |
|---|---|---|
| Telegram Reactions / Views / Votes / Comments / Shares | POST link | https://t.me/yourchannel/123 (ya post forward karo) |
| Telegram Members / Subscribers / Boosts | CHANNEL link | https://t.me/yourchannel  ya  @yourchannel |
| Telegram Auto Reactions / Auto Views [New/Old Post] | CHANNEL link | https://t.me/yourchannel |
| Telegram Bot Starts / Referral | BOT link | https://t.me/yourbot?start=ref123 |
| YouTube Views / Likes / Comments / Watch time | VIDEO link | https://youtu.be/dQw4w9WgXcQ |
| YouTube Subscribers | CHANNEL link | https://www.youtube.com/@yourchannel |
| YouTube Live viewers | LIVE link | https://youtube.com/live/xxxx |
| Instagram Followers | PROFILE link | https://www.instagram.com/yourusername |
| Instagram Likes / Views / Comments / Saves | POST/REEL link | https://www.instagram.com/reel/Cxxxx/ |
| Instagram Story views | PROFILE link | https://www.instagram.com/yourusername |
| TikTok / Facebook / X | video/post link | https://x.com/user/status/123 |

## Aapke screenshots me order CANCEL kyun hue
- "YouTube Subscribers" me `https://t.me/maaambey` diya tha -> Telegram link YouTube service me. Ab bot mana karega.
- "Telegram mix positive Reaction" me `https://t.me/sukoon_s` (channel link) diya tha -> reaction ko POST link chahiye (`https://t.me/sukoon_s/45`). Ab bot mana karega.

## Kya fix hua
1. Min / Max ab hamesha panel jaisa: service kholte hi aur order start par panel se live min/max aata hai; "Add SMM Service" me panel ID dalte hi min/max khud bhar jata hai.
2. Har service ke saath sahi link ka example dikhta hai; galat platform / channel-vs-post link reject.
3. Custom Comments services: bot comments (ek line = ek comment) maangta hai. Poll services: option number maangta hai.
4. `username` field ab har order me nahi bhejta (kuch panels isse cancel karte the).
5. Admin › 📊 Manage SMM ab kaam karta hai: pehle 1000+ services ek saath dikhane se button fail hota tha.
   Ab: Categories -> Services (pages) -> Show/Hide, Set Price, Delete, + Sync Panel, Panel Balance.
   Hide/Delete kiye services auto-sync me wapas nahi aate.
