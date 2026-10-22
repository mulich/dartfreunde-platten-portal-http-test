from playwright.sync_api import sync_playwright

from app.invitations import SCAN, joined


def test_actual_browser_scanner_uses_committed_membership_and_exact_notification():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.route('**/*',lambda route: route.fulfill(body='<main><button id="join">Annehmen</button></main>',content_type='text/html'))
        page.goto('https://play.autodarts.com/lobby/lobby-1')
        page.evaluate('''() => {
          const button=document.querySelector('#join');
          const current={stateNode:{},return:null};current.stateNode.current=current;
          const stale={stateNode:current.stateNode,return:null};
          const invite={type:'lobby:invite',id:'notice-1',body:{user:{id:'host',name:'Rot'},lobby:{id:'lobby-1'}}};
          const props={notification:invite,value:{id:'lobby-1',isPrivate:true,host:{id:'host'},players:[{userId:'own',isPending:false}]}};
          const committed={memoizedProps:props,return:current};
          button.__reactFiber$fixture={memoizedProps:{...props,value:{...props.value,players:[{userId:'own',isPending:true}]}},return:stale,alternate:committed};
          window.committed=committed;
        }''')
        invite={'lobby_id':'lobby-1','sender_id':'host'}
        snapshot=page.evaluate(SCAN)
        assert joined(snapshot,invite,'own')
        assert len(snapshot['invites'])==1
        page.evaluate('committed.memoizedProps.value.players[0].isPending=true')
        assert not joined(page.evaluate(SCAN),invite,'own')
        page.evaluate("committed.memoizedProps.notification.type='friend-list:request'")
        assert page.evaluate(SCAN)['invites']==[]
        browser.close()
