from aiohttp.web import Response, StreamResponse, HTTPBadRequest
from bson.json_util import dumps as bson_dumps, RELAXED_JSON_OPTIONS
from bson.objectid import ObjectId
from io import StringIO
from yarl import URL
import csv
import json
import re

from motor.aiohttp import AIOHTTPGridFS

from config import get_config

settings = get_config()


async def get_databases(request):
    data = {'data': [{'text': 'StringDB', 'value': 'stringdb'}]}
    headers = settings.get('HEADERS')
    return Response(body=json.dumps(data),
                    content_type="application/json",
                    headers=headers,
                    status=200)


async def get_aligners(request):
    enabled_aligners = sorted(['HubAlign', 'AligNet', 'PINALOG', 'SPINAL', 'L-GRAAL'])

    data = {
        'data': [{'text': a, 'value': a.lower()} for a in enabled_aligners]
    }

    headers = settings.get('HEADERS')
    return Response(body=json.dumps(data),
                    content_type="application/json",
                    headers=headers,
                    status=200)


async def get_networks(request):
    url = URL(settings.get('SOURCES_API_HOST'))
    db_name = request.match_info['db']

    if db_name.lower() == 'stringdb':
        url = url / 'db' / 'stringdb' / 'items' / 'species' / 'select'

        sess = request.sources_api_session
        req_headers = {'Accept': 'text/tab-separated-values'}

        sources_req = sess.post(url=url, json={'columns': ['species_id', 'official_name']}, headers=req_headers)

        async with sources_req as sources_resp:
            sources_resp.raise_for_status()
            species_rows = csv.reader(StringIO(await sources_resp.text()), delimiter='\t')
            next(species_rows) # skip header

            species = [
                {'text':f'{official_name} (NCBI: {species_id})', 'value': species_id}
                for species_id, official_name in species_rows
            ]
            species.sort(key = lambda item: item['text'])

        data = {'data': species}
    else:
        data = {'data': []}

    headers = settings.get('HEADERS')
    return Response(body=json.dumps(data),
                    content_type="application/json",
                    headers=headers,
                    status=200)


async def forward_streaming_request(request, new_request):
    async with new_request as resp:
        headers = settings.get('HEADERS')

        if resp.status < 400:
            resp2 = StreamResponse(headers=headers, status=200)
            resp2.content_type = resp.content_type
            resp2.content_length = resp.content_length

            await resp2.prepare(request)

            async for chunk, _ in resp.content.iter_chunks():
                await resp2.write(chunk)

            await resp2.write_eof()
            return resp2

        else:
            return Response(
                    body=await resp.read(),
                    content_type=resp.content_type,
                    headers=headers,
                    status=resp.status if resp.status >= 400 else 200)


async def get_species(request):
    url = URL(settings.get('SOURCES_API_HOST'))
    db = request.match_info['db']

    if db == 'stringdb':
        url = url / 'db' / 'stringdb' / 'items' / 'species' / 'select'
    else:
        raise HTTPBadRequest(text='DB not supported for request: ' + db)

    req_headers = {'Accept': request.headers.get('Accept', '*/*')}

    sess = request.sources_api_session

    return await forward_streaming_request(
            request,
            sess.post(url=url, json=request.post_json, headers=req_headers))


async def get_proteins(request):
    url = URL(settings.get('SOURCES_API_HOST'))
    db = request.match_info['db']

    if db == 'stringdb':
        url = url / 'db' / 'stringdb' / 'items' / 'proteins' / 'select'
    else:
        raise HTTPBadRequest(text='DB not supported for request: ' + db)

    req_headers = {'Accept': request.headers.get('Accept', '*/*')}

    sess = request.sources_api_session

    return await forward_streaming_request(
            request,
            sess.post(url=url, json=request.post_json, headers=req_headers))


async def get_network(request):
    url = URL(settings.get('SOURCES_API_HOST'))
    db = request.match_info['db']

    if db == 'stringdb':
        url = url / 'db' / 'stringdb' / 'network' / 'edges' / 'select'
    else:
        raise HTTPBadRequest(text='DB not supported for request: ' + db)

    req_headers = {'Accept': request.headers.get('Accept', '*/*')}

    sess = request.sources_api_session

    return await forward_streaming_request(
            request,
            sess.post(url=url, json=request.post_json, headers=req_headers))


async def get_weighted_network(request):
    url = URL(settings.get('SOURCES_API_HOST'))
    db = request.match_info['db']

    if db == 'stringdb':
        url = url / 'db' / 'stringdb' / 'network' / 'edges' / 'weighted'
    else:
        raise HTTPBadRequest(text='DB not supported for request: ' + db)

    req_headers = {'Accept': request.headers.get('Accept', '*/*')}

    sess = request.sources_api_session

    return await forward_streaming_request(
            request,
            sess.get(url=url, params=request.rel_url.query, headers=req_headers))


async def get_mongo_alignment(request):
    obj_id = request.match_info['result_id']
    res = await request.app['mongo_db'].alignments.find_one({'_id': ObjectId(obj_id)})

    headers = settings.get('HEADERS')
    return Response(body=bson_dumps(res, json_options=RELAXED_JSON_OPTIONS),
                    content_type="application/json",
                    headers=headers,
                    status=200)


async def get_mongo_comparison(request):
    obj_id = request.match_info['result_id']
    res = await request.app['mongo_db'].comparisons.find_one({'_id': ObjectId(obj_id)})

    headers = settings.get('HEADERS')
    return Response(body=bson_dumps(res, json_options=RELAXED_JSON_OPTIONS),
                    content_type="application/json",
                    headers=headers,
                    status=200)


class GetMongoFileHandler(AIOHTTPGridFS):
    def __init__(self):
        pass

    def _get_gridfs_file(self, bucket, filename, request):
        return bucket.open_download_stream(file_id = ObjectId(filename))

    def _get_cache_time(self, filename, modified, mime_type):
        return 0

    def _set_extra_headers(self, response, gridout):
        response.headers['Content-Disposition'] = 'attachment; filename="' + re.sub(r'^(.*)_(.*?)$', r'\1.\2', gridout.filename) + '"'

    def _init_base(self, request):
        self._database = request.app['mongo_db']
        self._bucket = request.app['mongo_gridfs']
        self._get_gridfs_file = self._get_gridfs_file
        self._get_cache_time = self._get_cache_time
        self._set_extra_headers = self._set_extra_headers

    async def __call__(self, request):
        self._init_base(request)
        return await super().__call__(request)

get_mongo_file = GetMongoFileHandler()

# async def get_mongo_file(request):
#     mongodb = request.app['mongo_db']
#     mongo_gridfs = request.app['mongo_gridfs']
#
#     handler = AIOHTTPGridFS(mongodb, get_gridfs_file=get_gridfs_file_by_id)
#
#     response = await handler(request)
#     return response
#
