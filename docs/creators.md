# Infield / Approach Creators (Meta Glasses)

Big Instagram accounts posting cold-approach "infield" clips filmed on Ray-Ban Meta
smart glasses. Source pool for trainer clips. Identified via press coverage
(CNN, Miami New Times, 404 Media, SFist), June 2026.

## The accounts

| Handle                                                         | Name                                | Followers | Notes                                                                                   |
| -------------------------------------------------------------- | ----------------------------------- | --------- | --------------------------------------------------------------------------------------- |
| [@itspolokidd](https://www.instagram.com/itspolokidd/)         | Sayed "Polokid" Kaghazi (Miami)     | ~1.5–2M   | Exclusively covert number-close clips on Meta glasses; 2,700+ posts, ~3 yrs of material |
| [@tristansocial](https://www.instagram.com/tristansocial/)     | Tristan Yoder, "The Approach Coach" | ~1M       | Infield approach/number-close clips + coaching; confirmed the right "Tristan"           |
| [@rizzzcam](https://www.instagram.com/rizzzcam/)               | Cameron John                        | ~950K     | Beach/night-out approaches on Meta glasses; also livestreams on Kick                    |
| [@pickuplines.pov](https://www.instagram.com/pickuplines.pov/) | —                                   | smaller   | TikTok + IG; the USF campus-alert account                                               |

## Sample reel URLs (yt-dlp verified working on direct /reel/ links)

- https://www.instagram.com/itspolokidd/reel/DHHmohEOYGJ/ — "Hitting on Florida moms!"
- https://www.instagram.com/itspolokidd/reel/DHCmxs_vGAZ/ — "Greek girls"
- https://www.instagram.com/itspolokidd/reel/DCNs124vBot/ — "How it goes!"
- https://www.instagram.com/itspolokidd/reel/DHcH4muOxJt/ — "Lexi da baddie!"

## Source articles

- [CNN — "Manfluencers" + smart glasses](https://www.cnn.com/2026/02/09/world/manfluencers-smart-glasses-intl) (Feb 2026)
- [Miami New Times — profile of @itspolokidd](https://www.miaminewtimes.com/arts-culture/i-was-secretly-filmed-by-viral-miami-pickup-artist-23662730/)
- [404 Media — Meta glasses harassment reporting](https://www.404media.co/metas-ray-ban-glasses-users-film-and-harass-massage-parlor-workers/)
- [SFist — USF alert re: @pickuplines.pov](https://sfist.com/2025/10/03/here-come-the-creeps-meta-ray-ban-glasses-dudebro-stalking-women-at-usf-posting-videos-of-them-to-social-media/)

## Notes for clip ingestion

- `yt-dlp` works on direct `https://www.instagram.com/<user>/reel/<id>/` URLs without
  login (public posts). Profile/reels listing pages are NOT supported — collect reel
  URLs individually (web search, or saved-posts export with cookies).
- For saved posts: `yt-dlp --cookies-from-browser` against the saved collection would
  need Instagram login cookies.
