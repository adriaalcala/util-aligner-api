from aiohttp.web import Response
import json

from api.aligner import server_create_job, server_finished_job
from api.v2.request import adapt_data

from config import get_config

settings = get_config()

async def create_job(request):
    data = request.post_json
    data = adapt_data(data)
    job_id = await server_create_job(request.app['master_pool'],
                                     request.app['redis_pool'], request.app['celery'],
                                     request.app['mongo_db'], request.app['mongo_gridfs'],
                                     data)

    headers = settings.get('HEADERS')
    return Response(body=json.dumps({'job_id': job_id}),
                    content_type='application/json',
                    headers=headers,
                    status=200)


async def finished_job(request):
    data = request.post_json
    await server_finished_job(request.app['mongo_db'], request.app['mongo_gridfs'],
                              request.app['redis_pool'], data['job_id'],
                              data['result_id'])
    return Response(status=200)