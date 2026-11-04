const { test,expect }=require('@playwright/test');

test('real HEVC software fallback decodes through trusted HTTPS and restarts after teardown',async({page,context,baseURL},testInfo)=>{
  const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  context.on('request',request=>requests.push(request.url()));
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(['blob:','data:','about:'].includes(url.protocol)||url.origin===new URL(baseURL).origin)return route.continue();
    errors.push('Unexpected external request: '+url.origin+url.pathname);return route.abort('blockedbyclient');
  });
  await page.goto('/__qa/admin');
  await expect(page.locator('#wall-grid')).toBeVisible();
  expect(await page.evaluate(()=>({secure:isSecureContext,protocol:location.protocol}))).toEqual({secure:true,protocol:'https:'});
  const capabilities=await page.request.get('/api/live/capabilities?cam_id=demo_0&stream=sub');
  expect(capabilities.ok()).toBeTruthy();
  expect(await capabilities.json()).toMatchObject({hevc_support:true,live_video:{codec:'hevc',codec_string:null,container:'fmp4'}});
  async function playing(){
    await page.getByRole('button',{name:'1 окно',exact:true}).click();
    await expect(page.locator('#wall-grid video')).toHaveCount(1);
    const video=page.locator('#wall-grid video');
    await expect.poll(()=>video.evaluate(v=>v.videoWidth),{timeout:45000}).toBe(320);
    await expect.poll(()=>video.evaluate(v=>v.currentTime),{timeout:45000}).toBeGreaterThan(.5);
    await expect(page.locator('#wall-grid .wall-stream-status')).toHaveAttribute('data-state','playing');
    expect(await video.evaluate(v=>v.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(3);
    return video;
  }
  const video=await playing();
  for(const asset of ['/static/vendor/hevc-plugin.js','/static/vendor/hevc/transcode-worker.js','/static/vendor/hevc/hevc-decode.wasm']){
    await expect.poll(()=>requests.some(value=>new URL(value).pathname===asset),{timeout:15000}).toBe(true);
  }
  await testInfo.attach('decoded-hevc',{body:await page.screenshot(),contentType:'image/png'});
  const old=await video.elementHandle();
  await page.locator('#navigation [data-view="archive"]').click();
  await expect(page.locator('#arc-camera')).toBeVisible();
  expect(await old.evaluate(v=>v.paused&&!v.getAttribute('src'))).toBe(true);
  await page.locator('#navigation [data-view="live"]').click();
  await expect(page.locator('#wall-grid')).toBeVisible();
  await playing();
  await testInfo.attach('hevc-evidence',{body:JSON.stringify({project:testInfo.project.name,errors,requests},null,2),contentType:'application/json'});
  expect(errors).toEqual([]);
});
