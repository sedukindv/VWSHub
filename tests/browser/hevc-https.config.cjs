const { defineConfig } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
if (!process.env.WVW_BROWSER_CERT || !process.env.WVW_BROWSER_KEY) throw Error('Provide disposable QA TLS identity; see README');
const port=5291, baseURL=`https://127.0.0.1:${port}`;
const data=fs.mkdtempSync(path.join(os.tmpdir(),'wvw-hevc-browser-'));
module.exports=defineConfig({
  testDir:__dirname,testMatch:'hevc-https.spec.cjs',workers:1,fullyParallel:false,retries:0,timeout:90000,
  reporter:[['list'],['html',{open:'never',outputFolder:'hevc-playwright-report'}]],
  outputDir:path.join(__dirname,'hevc-test-results'),
  use:{baseURL,headless:true,ignoreHTTPSErrors:false,viewport:{width:1248,height:960},locale:'ru-RU',trace:'retain-on-failure',screenshot:'only-on-failure',serviceWorkers:'block'},
  projects:[{name:'chrome-hevc',use:{browserName:'chromium',channel:'chrome'}},{name:'edge-hevc',use:{browserName:'chromium',channel:'msedge'}}],
  webServer:{command:`"${process.env.WVW_PYTHON||'python'}" "${path.join(__dirname,'fixture_server.py')}"`,cwd:__dirname,url:`${baseURL}/health`,timeout:120000,reuseExistingServer:false,stdout:'ignore',stderr:'pipe',
    env:{WVW_BROWSER_HEVC:'1',WVW_BROWSER_PORT:String(port),WVW_BROWSER_DATA:data,WVW_BROWSER_SETUP:'0',PYTHONIOENCODING:'utf-8'}},
});
