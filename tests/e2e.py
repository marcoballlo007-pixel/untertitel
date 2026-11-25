import asyncio, base64, sys, subprocess, json, psutil

peak={'mb':0}
async def watch_mem(stop):
    while not stop.is_set():
        tot=0
        for pr in psutil.process_iter(['name','cmdline']):
            try:
                c=' '.join(pr.info['cmdline'] or [])
                if 'WebKit' in c or 'webkit' in c.lower() or 'chrome' in c.lower():
                    tot+=pr.memory_info().rss
            except Exception: pass
        peak['mb']=max(peak['mb'],tot/1e6)
        await asyncio.sleep(0.5)

from playwright.async_api import async_playwright

async def run(p, browser_name, media, lang="german", model=None, ipad=False):
    bt = getattr(p, browser_name)
    peak["mb"]=0; stop=asyncio.Event(); wt=asyncio.create_task(watch_mem(stop))
    args = ["--autoplay-policy=no-user-gesture-required"] if browser_name == "chromium" else []
    b = await bt.launch(args=args)
    pg = await (b.new_page(**p.devices["iPad Pro 11"]) if ipad else b.new_page())
    logs = []
    pg.on("console", lambda m: logs.append(m.text))
    pg.on("pageerror", lambda e: logs.append("PAGEERROR " + str(e)))
    if not ipad: await pg.set_viewport_size({"width":820,"height":1180})
    await pg.goto("http://localhost:8000/index.html")
    await asyncio.sleep(2)
    await pg.screenshot(path=f"out/{browser_name}{'_ipad' if ipad else ''}_start.png")
    await pg.select_option("#lang", lang)
    if model: await pg.evaluate("m=>{document.getElementById('model').value=m}", model)
    await pg.set_input_files("#file", media)
    await pg.click("#go")
    s = ""
    for i in range(600):
        await asyncio.sleep(1)
        s = await pg.text_content("#status")
        if s.startswith("Fertig") or s.startswith("Fehler"):
            break
    caps = await pg.evaluate("[...document.querySelectorAll('.it textarea')].map(t=>t.value)")
    stop.set(); await wt
    print(f"\n===== {browser_name}{' (iPad)' if ipad else ''} · {media} =====")
    print("PEAK-SPEICHER MB:", round(peak["mb"]))
    print("STATUS:", s)
    print("CAPTIONS:", json.dumps(caps, ensure_ascii=False))
    print("APPLOG:\n" + (await pg.text_content("#log")))
    await pg.screenshot(path=f"out/{browser_name}{'_ipad' if ipad else ''}_fertig.png")
    ok = s.startswith("Fertig") and len(caps) > 0
    if ok:
        d = await pg.evaluate("""async()=>{const r=window.__result;const buf=new Uint8Array(await r.blob.arrayBuffer());let s='';for(let i=0;i<buf.length;i+=8192)s+=String.fromCharCode.apply(null,buf.subarray(i,i+8192));return [r.name,btoa(s)]}""")
        out = f"out/{browser_name}{'_ipad' if ipad else ''}_{d[0]}"
        open(out, "wb").write(base64.b64decode(d[1]))
        print("VIDEO:", out)
        print(subprocess.run(["ffprobe","-v","error","-show_entries","stream=codec_type,codec_name:format=duration","-of","compact",out],capture_output=True,text=True).stdout)
        subprocess.run(["ffmpeg","-loglevel","error","-y","-i",out,"-vf","select=gte(t\\,2)","-frames:v","1",out+".png"])
    await b.close()
    return ok

async def main():
    results = {}
    async with async_playwright() as p:
        for br in ["chromium", "webkit"]:
            for m in ["media/speech.mp4", "media/song.mp4"]:
                try:
                    results[f"{br} {m}"] = await run(p, br, m)
                except Exception as e:
                    print(f"\n===== {br} {m} CRASH: {e}")
                    results[f"{br} {m}"] = False
        try:
            results["ipad long"] = await run(p, "webkit", "media/long.mp4", ipad=True)
        except Exception as e:
            print("ipad CRASH", e)
        try:
            results["webkit small song"] = await run(p, "webkit", "media/song.mp4", model="onnx-community/whisper-small")
        except Exception as e:
            print("small CRASH", e)
    print("\nRESULTS:", json.dumps(results))
    sys.exit(0 if results.get("chromium media/speech.mp4") else 1)

asyncio.run(main())
