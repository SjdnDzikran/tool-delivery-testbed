"""Run unchanged upstream verifier; adapt only Chrome binary/sandbox deployment."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
from playwright.async_api import BrowserType


async def run(reference,messages):
    original=BrowserType.launch
    async def launch(self,*args,**kwargs):
        if self.name!='chromium':raise ValueError('Only pinned Chrome authorized')
        kwargs.update(executable_path='/opt/google/chrome/chrome',chromium_sandbox=True)
        browser=await original(self,*args,**kwargs)
        if browser.version!='156.0.8078.79':
            await browser.close();raise ValueError('Chrome identity mismatch')
        return browser
    BrowserType.launch=launch
    os.environ['WEBARENA_BASE_URL']='http://shopping/admin'
    os.environ['MCP_MESSAGES']=str(messages)
    try:
        spec=importlib.util.spec_from_file_location('original_shopping_verifier',reference)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return bool(await module.verify())
    finally:
        BrowserType.launch=original


if __name__=='__main__':
    sys.exit(0 if asyncio.run(run(Path(sys.argv[1]),Path(sys.argv[2]))) else 1)
