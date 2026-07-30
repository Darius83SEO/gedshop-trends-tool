import config; config.JSON_STORAGE_PATH='data/store.json'
from storage import get_storage
import analysis
from providers.dataforseo import DataForSEOProvider
from gedshop_seed import GEDSHOP_CATEGORIES, SITE_URL
st=get_storage(); prov=DataForSEOProvider(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD)
for cat in GEDSHOP_CATEGORIES:
    cid=st.upsert_category(SITE_URL, cat['name'], cat['query_term'], 'IT', url=cat.get('url'))
    try:
        rec=analysis.analyze_category(prov, cat['name'], cat['query_term'], 'IT')
        if rec.get('term') or rec.get('topic'):
            st.save_record(cid, rec)
            v=rec[rec['active_mode']]
            print(f"{cat['name']:22} {rec['active_mode']:5} picco={v['peak']:2} pubblica={v['pub']:2} forza={int(v['strength']*100)}%")
        else:
            print(f"{cat['name']:22} NESSUN DATO")
    except Exception as e:
        print(f"{cat['name']:22} ERR {e}")
print("STORE POPOLATO")
