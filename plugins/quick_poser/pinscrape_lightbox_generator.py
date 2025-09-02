import datetime
import json
import logging
import multiprocessing
import random
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from operator import itemgetter
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile

import requests
from PIL import Image, ImageOps, UnidentifiedImageError
from bs4 import BeautifulSoup as soup
from openai import OpenAI
from pelican import signals
from pelican.contents import Article
from pelican.readers import BaseReader
import urllib.parse

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0'


class PinterestImageScraper:
    @staticmethod
    def get_pinterest_links(body):
        html = soup(body, 'html.parser')
        links = html.select('.dgControl .iusc')
        all_urls = [json.loads(link.get('m', '{}')).get('murl', '') for link in links]
        pinterest_urls = {l for l in all_urls if 'pinterest' in l or 'i.pinimg.com' in l}
        return list(pinterest_urls), all_urls

    @staticmethod
    def start_scraping(query, proxies: dict = None):
        query_param = urllib.parse.quote_plus(f'{query} pinterest')
        url = f'https://www.bing.com/images/search?q={query_param}&first=1&FORM=HDRSC3'
        res = requests.get(url, proxies=proxies, headers={'User-Agent': USER_AGENT})
        res.raise_for_status()
        return PinterestImageScraper.get_pinterest_links(res.content)

    def scrape(self, query: str, tmppath: Path, threads: int = 2, max_images: int = 1, proxies: dict = None) -> [str]:
        pinterest_urls, all_urls = PinterestImageScraper.start_scraping(query, proxies)
        print(f'Found {len(pinterest_urls)} links from {len(all_urls)} for {query}')

        pinterest_urls = pinterest_urls[:max_images]
        with ThreadPoolExecutor(max_workers=threads) as executor:
            counts = executor.map(self.download, *[
                (pinterest_urls[i:i + threads]
                 for i in range(0, len(pinterest_urls), threads)),
                [tmppath] * threads
            ])
            executor.shutdown(wait=True)

        return pinterest_urls, sum(counts)

    @staticmethod
    def download(url_list, tmppath) -> int:
        counts = 0
        for url in url_list:
            with NamedTemporaryFile(dir=tmppath, suffix='.jpg', delete=False) as fp:
                r = requests.get(url, stream=True)
                if r.ok:
                    shutil.copyfileobj(r.raw, fp)
                    fp.close()
                    try:
                        im = Image.open(fp.name)
                        im = ImageOps.exif_transpose(im)
                        rgb_im = im.convert('RGB')
                        rgb_im.save(fp.name)
                        counts += 1
                    except UnidentifiedImageError as e:
                        pass

        return counts


scraper = PinterestImageScraper()


def _get_queries_per_category(pinscrape_categories,
                              openai_api_key, openai_model_name, openai_system_prompt, openai_user_prompt,
                              number_of_queries=3) -> list[tuple[str, str]]:
    client = OpenAI(api_key=openai_api_key)

    messages = []
    if openai_system_prompt:
        messages.append({'role': 'system', 'content': openai_system_prompt})

    category_hints = '\n'.join(f'Category: {k}, search hint: {v}' for k, v in pinscrape_categories.items())

    messages.append({'role': 'user', 'content': openai_user_prompt.format(category_hints=category_hints)})

    print(messages)

    completion = client.chat.completions.create(
        model=openai_model_name, messages=messages, response_format={'type': 'json_object'})

    search_queries = json.loads(completion.choices[0].message.content)
    assert search_queries, 'No search queries loaded'

    search_queries = {
        category: random.choices(search_queries, k=number_of_queries)
        for category, search_queries in search_queries.items()
    }
    return list(search_queries.items())


def _download(category: str, query: str, max_images: int, categories: [str], tmppath: Path):
    download_filepaths = []
    if categories and category not in categories:
        print(f'Skipping query {query}, category {category} is not whitelisted')
        return download_filepaths

    try:
        pinterest_urls, downloaded_count = scraper.scrape(query, tmppath, multiprocessing.cpu_count(), max_images)
    except Exception as ex:
        logging.exception(str(ex))
        raise RuntimeError from ex

    if pinterest_urls:
        print(f'Found {len(pinterest_urls)} urls for query {query}, downloaded {downloaded_count}')
        download_filepaths = list(tmppath.iterdir())
        print(f'Downloaded {len(download_filepaths)} files')
    else:
        print(f'Skipping query {query}, nothing downloaded')
    return download_filepaths


def add_article(article_generator):
    settings = article_generator.settings

    (
        pinscrape_categories,
        content_path,
        images_path,
        images_number_per_category,
        categories,
        openai_api_key,
        openai_model_name,
        openai_system_prompt,
        openai_user_prompt,
    ) = itemgetter(
        'PINSCRAPE_CATEGORIES',
        'PATH',
        'IMAGES_PATH',
        'IMAGES_NUMBER_PER_CATEGORY',
        'CATEGORIES',
        'OPENAI_API_KEY',
        'OPENAI_MODEL_NAME',
        'OPENAI_SYSTEM_PROMPT',
        'OPENAI_USER_PROMPT',
    )(settings)

    queries = _get_queries_per_category(pinscrape_categories,
                                        openai_api_key, openai_model_name, openai_system_prompt, openai_user_prompt,
                                        number_of_queries=3)
    queries = [(category, query) for category, category_queries in queries for query in category_queries]

    with TemporaryDirectory() as tmpdir:
        root_tmppath = Path(tmpdir)
        download_filepaths = defaultdict(list)
        for query_idx, (category, query) in enumerate(queries):
            tmppath = root_tmppath.joinpath(f'{category}{query_idx}')
            tmppath.mkdir(parents=True, exist_ok=True)
            download_filepaths[category].extend(_download(
                category, query, images_number_per_category * 3, categories, tmppath))

        base_reader = BaseReader(settings)

        for category, image_filepaths in download_filepaths.items():
            selected_images = random.sample(image_filepaths, min(len(image_filepaths), images_number_per_category))

            print(
                f'Category {category} has total images count: {len(image_filepaths)}, '
                f'needed: {images_number_per_category}, selected: {len(selected_images)}')

            images = []
            for image_tmp_filepath in selected_images:
                image_path = f'{category}/{image_tmp_filepath.name}'
                image_filepath = content_path / Path(images_path) / image_path
                image_filepath.parent.mkdir(parents=True, exist_ok=True)
                image_url = f'{images_path}/{image_path}'
                images.append(image_url)
                shutil.move(image_tmp_filepath, image_filepath)

            if images:
                print(f'Selected images count: {len(images)}')
                new_article = Article('', {
                    'template': 'lightbox',
                    'title': category,
                    'date': datetime.datetime.now(),
                    'category': base_reader.process_metadata('category', category),
                    'images': images,
                })
                article_generator.articles.insert(0, new_article)
            else:
                print(f'No images selected for {category}, skipping article')


def register():
    signals.article_generator_pretaxonomy.connect(add_article)
