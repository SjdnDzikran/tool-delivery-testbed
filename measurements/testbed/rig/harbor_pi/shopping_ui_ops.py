"""Trusted UI oracle/probe, never a skill or model-facing resource."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
from playwright.async_api import async_playwright

OUT=Path('/home/study/probe-output')
BASE='http://shopping/admin'


async def dump(page,name):
    (OUT/(name+'.txt')).write_text(await page.locator('body').inner_text())
    (OUT/(name+'.aria.txt')).write_text(await page.locator('body').aria_snapshot())
    (OUT/(name+'.inputs.json')).write_text(json.dumps(await page.locator('input,select,button').evaluate_all(
        "els => els.map(e=>({tag:e.tagName,id:e.id,name:e.name,type:e.type,text:e.innerText,placeholder:e.getAttribute('placeholder'),ariaLabel:e.getAttribute('aria-label')}))"),indent=2))
    (OUT/(name+'.tables.json')).write_text(json.dumps(await tables(page),indent=2))
    await page.screenshot(path=str(OUT/(name+'.png')),full_page=True)


async def settle(page):
    await page.wait_for_load_state('networkidle')
    await page.wait_for_timeout(1000)
    await page.locator('.admin__data-grid-loading-mask').first.wait_for(state='hidden')


async def visit(page,path):
    await page.goto(BASE+'/'+path,wait_until='networkidle')
    await settle(page)


async def records(page):
    text=await page.locator('body').inner_text()
    match=re.search(r'(\d+)\s+records?\s+found',text,re.I)
    if not match:raise RuntimeError('Visible records-found counter absent')
    return int(match[1])


async def filters(page):
    group=page.get_by_role('group',name='Advanced filter',exact=True)
    if not await group.is_visible():
        await page.get_by_role('button',name=re.compile(r'^[^A-Za-z]*Filters$')).click()
    await group.wait_for()


async def apply(page):
    async with page.expect_response(lambda r:'/mui/index/render/' in r.url) as pending:
        await page.get_by_role('button',name='Apply Filters',exact=True).click()
    response=await pending.value
    await response.finished()
    if response.status!=200:raise RuntimeError('Grid filter HTTP '+str(response.status))
    await settle(page)


async def clear(page,expected_records):
    button=page.get_by_role('button',name=re.compile('Clear all',re.I))
    if await button.count():
        await button.first.click()
        await page.wait_for_function(r"n => document.body.innerText.match(/(\d+)\s+records?\s+found/i)?.[1] === String(n)",arg=expected_records)
        await settle(page)


async def tables(page):
    result=[]
    for table in await page.get_by_role('table').all():
        headers=[s.strip() for s in await table.get_by_role('columnheader').all_inner_texts()]
        rows=[]
        for row in await table.get_by_role('row').all():
            cells=[s.strip() for s in await row.get_by_role('cell').all_inner_texts()]
            if cells:rows.append(cells)
        result.append({'headers':headers,'rows':rows})
    return result


def money(value):
    return Decimal(value.replace('$','').replace(',','').strip())


async def segmentation(page):
    values={}
    await visit(page,'customer/group/')
    values['InitialGroups']=await records(page)
    await page.get_by_role('button',name='Add New Customer Group',exact=True).click()
    await settle(page)
    await page.get_by_role('textbox',name=re.compile('^Group Name')).fill('Premium Europe')
    await page.get_by_role('combobox',name=re.compile('^Tax Class')).select_option(label='Retail Customer')
    await page.get_by_role('button',name='Save Customer Group',exact=True).click()
    await settle(page)
    await visit(page,'customer/group/')
    values['FinalGroups']=await records(page)
    await dump(page,'created-group')
    await visit(page,'customer/index/')
    values['InitialCustomers']=await records(page)
    await visit(page,'customer/index/new/')
    await page.locator('select[name="customer[website_id]"]').select_option(label='Main Website')
    await page.locator('select[name="customer[group_id]"]').select_option(label='Premium Europe')
    await page.get_by_role('textbox',name=re.compile('^First Name')).fill('Isabella')
    await page.get_by_role('textbox',name=re.compile('^Last Name')).fill('Romano')
    await page.get_by_role('textbox',name=re.compile('^Email')).fill('isabella.romano@premium.eu')
    await page.get_by_role('button',name='Save Customer',exact=True).click()
    await settle(page)
    await visit(page,'customer/index/')
    values['FinalCustomers']=await records(page)
    await dump(page,'created-customer')
    await visit(page,'admin/dashboard/')
    table=next(t for t in await tables(page) if t['headers']==['Customer','Items','Total'])
    values['LastOrderCustomer']=table['rows'][-1][0]
    return values


async def products(page):
    values={}
    await visit(page,'catalog/product/')
    product_total=await records(page)
    await filters(page)
    await page.get_by_role('textbox',name='Name',exact=True).fill('Yoga')
    await apply(page)
    values['YogaProducts']=await records(page)
    await dump(page,'yoga-filter')
    await clear(page,product_total)
    await filters(page)
    await page.get_by_role('textbox',name='SKU',exact=True).fill('WH11')
    await apply(page)
    await dump(page,'sku-filter')
    table=next(t for t in await tables(page) if 'SKU' in t['headers'] and 'Price' in t['headers'])
    sku=table['headers'].index('SKU');price=table['headers'].index('Price')
    row=next(r for r in table['rows'] if r[sku]=='WH11')
    values['WH11Price']=row[price]
    await dump(page,'sku-filter')
    await clear(page,product_total)
    await filters(page)
    qty=page.get_by_role('group',name='Quantity',exact=True)
    await qty.get_by_role('textbox',name='from',exact=True).fill('0.0000')
    await qty.get_by_role('textbox',name='to',exact=True).fill('0.0000')
    await apply(page)
    values['ZeroQuantityProducts']=await records(page)
    await dump(page,'zero-quantity-filter')
    await visit(page,'admin/dashboard/')
    table=next(t for t in await tables(page) if t['headers']==['Product','Price','Quantity'])
    best=min(table['rows'],key=lambda r:(int(r[2]),money(r[1])))
    values['LowestProduct']=best[0]+':'+best[2]
    values['SecondCheapestQuantity']=sorted(table['rows'],key=lambda r:money(r[1]))[1][2]
    text=await page.locator('main').inner_text()
    values['DashboardRevenue']=re.search(r'Revenue\s+(\$[\d,.]+)',text)[1]
    await visit(page,'customer/index/')
    values['TotalCustomers']=await records(page)
    keyword=page.get_by_role('textbox',name='Search by keyword',exact=True)
    await keyword.fill('Sarah Miller')
    async with page.expect_response(lambda r:'/mui/index/render/' in r.url) as pending:
        await keyword.press('Enter')
    await (await pending.value).finished();await settle(page)
    await dump(page,'sarah-filter')
    table=next(t for t in await tables(page) if 'Email' in t['headers'])
    row=next(r for r in table['rows'] if 'Sarah Miller' in r)
    values['SarahMillerEmail']=row[table['headers'].index('Email')]
    await visit(page,'sales/order/')
    order_total=await records(page)
    await filters(page)
    await page.locator('select[name="status"]').first.select_option(label='Pending')
    await apply(page)
    values['PendingOrders']=await records(page)
    await dump(page,'pending-filter')
    await clear(page,order_total)
    await filters(page)
    await page.get_by_role('textbox',name='Bill-to Name',exact=True).fill('Grace Nguyen')
    await page.locator('select[name="status"]').first.select_option(label='Complete')
    await apply(page)
    table=next(t for t in await tables(page) if 'Grand Total (Base)' in t['headers'])
    if len(table['rows'])!=await records(page):raise RuntimeError('Filtered orders require pagination')
    cost=table['headers'].index('Grand Total (Base)');order_id=table['headers'].index('ID')
    values['GraceNguyenOrderID']=max(table['rows'],key=lambda r:money(r[cost]))[order_id]
    await dump(page,'grace-filter')
    return values


async def inspect(page):
    values={}
    for name,path in [('groups','customer/group/'),('customers','customer/index/'),
                      ('products','catalog/product/'),('orders','sales/order/')]:
        await visit(page,path);await dump(page,name)
        values[name]={'url':page.url,'records':await records(page)}
    for name,path in [('new-group','customer/group/new/'),('new-customer','customer/index/new/')]:
        await visit(page,path);await dump(page,name)
    await visit(page,'catalog/product/');await filters(page);await dump(page,'product-filters')
    await visit(page,'sales/order/');await filters(page);await dump(page,'order-filters')
    return values


async def main():
    OUT.mkdir()
    operation=sys.argv[1]
    result={'operation':operation,'model_calls':0,'browser_sandbox':True}
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,chromium_sandbox=True)
            result['chrome_version']=browser.version
            if not browser.version.startswith('156.0.8078.79'):raise RuntimeError('Pinned Chrome version differs')
            context=await browser.new_context(viewport={'width':1440,'height':1000})
            page=await context.new_page();page.set_default_timeout(30000)
            await page.goto(BASE+'/',wait_until='networkidle')
            if await page.locator('input[name="login[username]"]').count():
                await page.locator('input[name="login[username]"]').fill('admin')
                await page.locator('input[name="login[password]"]').fill('admin1234')
                await page.get_by_role('button',name='Sign in',exact=True).click()
                await page.wait_for_load_state('networkidle')
            result['dashboard_reached']='dashboard' in page.url.lower();await dump(page,'dashboard')
            if not result['dashboard_reached']:raise RuntimeError('Admin dashboard not reached')
            result['values']=await {'inspect':inspect,'segmentation':segmentation,'products':products}[operation](page)
            if operation!='inspect':
                text='<answer>\n'+'\n'.join(k+'|'+str(v) for k,v in result['values'].items())+'\n</answer>'
                (OUT/'oracle-messages.json').write_text(json.dumps([{'role':'assistant','status':'completed',
                    'type':'message','content':[{'type':'output_text','text':text}]}])+'\n')
            await context.close();await browser.close();result['completed']=True
    except Exception as exc:
        result['error_type']=type(exc).__name__;result['error']=str(exc)
        raise
    finally:
        (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':asyncio.run(main())
