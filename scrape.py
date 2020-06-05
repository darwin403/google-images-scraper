import base64
import io
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

import coloredlogs
from bs4 import BeautifulSoup
from google.cloud import vision
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

coloredlogs.install(
    fmt='%(asctime)s [%(programname)s] %(levelname)s %(message)s')

SAVE_ROOT = Path.cwd()
PROJECT_ROOT = Path(__file__).parent.resolve()

# Set Google Vision API
if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    try:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(
            PROJECT_ROOT / 'google_api_key.json')
    except Exception as e:
        logging.critical('[vision]: no google_api_key.json found. message: %s' % e)


def find_images(keyword, category):
    """A function that scrapes the urls of first 100 images from google by given keywords.

    Args:
        keyword (str): The exact keyword to search for.
        category (str): The exact category to search for.

    Returns:
        list: A list of tuples. Wherein for each tuple, the first element is an image's thumbnail and the second element is an image's original url.
    """

    # url = 'https://www.google.com/search?as_st=y&tbm=isch&hl=en&as_q=&as_epq=%s,%s&as_oq=&as_eq=meme&cr=&as_sitesearch=&safe=images&tbs=itp:animated,iar:xw' % (
    #     urllib.parse.quote_plus(keyword), urllib.parse.quote_plus(category))
    url = 'https://www.google.com/search?as_st=y&tbm=isch&hl=en&as_q=&as_epq=%s&as_oq=&as_eq=2077&cr=&as_sitesearch=&tbs=itp:animated' % (
        urllib.parse.quote_plus(keyword))

    options = webdriver.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument("--start-maximized")
    # options.add_argument("--force-device-scale-factor=0.05")
    # options.add_argument('--headless')

    browser = webdriver.Chrome(
        ChromeDriverManager().install(), options=options)

    browser.get(url)

    logging.info('[chrome] webpage: opened %s' % url)

    # scroll down to load all images
    scroll = True
    height = browser.execute_script("return document.body.scrollHeight")
    while scroll:
        browser.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);")

        time.sleep(3)

        new_height = browser.execute_script(
            "return document.body.scrollHeight")

        # click on show more results button if visible
        if new_height == height:
            try:
                button = WebDriverWait(browser, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'input.mye4qd')))
                button.click()
            except:
                break

        logging.info('[chrome] webpage: scrolling')
        height = new_height

    logging.info('[chrome] webpage: clicking on all images')

    # generate all original urls available by clicking on each
    images_el = browser.find_elements_by_css_selector(
        'a[jsaction="click:J9iaEb;"]')
    for el in images_el:
        try:
            if el.is_displayed():
                el.click()
        except:
            # since there is a javascript issue on google's page that hides some elements
            continue

    page_source = browser.page_source

    # close browser
    browser.quit()

    # load html markup
    soup = BeautifulSoup(page_source, 'html.parser')

    # choose all selectors for images
    ori_images = soup.select('a[jsaction="click:J9iaEb;"]')
    thumb_images = soup.select('img[jsname="Q4LuWd"]')

    # extract all image urls from each selector
    ori_urls = [re.search(r'imgurl=(.*)&imgrefur', unquote(link.get('href')),
                          flags=re.I).group(1) for link in ori_images if link.get('href')]
    thumb_urls = [image.get('src') or image.get('data-src')
                  for image in thumb_images]

    logging.info('[chrome] webpage: gathered %s urls' % len(ori_urls))

    return [[i, j] for (i, j) in zip(thumb_urls, ori_urls)]


def detect_text(path):
    """Detects if any kind of text is present in a given image by using Google Vision API.

    Args:
        path (str): The path of the image file on your filesystem.

    Returns:
        bool: A boolean based on if the given image has any text or not.
    """

    try:
        client = vision.ImageAnnotatorClient()

        with io.open(path, 'rb') as image_file:
            content = image_file.read()

        # pylint: disable=no-member
        image = vision.types.Image(content=content)
        response = client.text_detection(image=image)

        if response.error.message:
            logging.error('[vision] message: %s' % response.error.message)
            return False

        # found text in image
        if response.text_annotations:
            return True

    except Exception as e:
        logging.error('[vision] message: %s' % e)

    return False


def download_image(url, loc):
    """Download an arbitrary image, may it be base64 URI or a standard URL.

    Args:
        url (str): The remote image URL or base64 encoded URL to download.
        loc (str): The file path to be saved at. This excludes the file extension as it is will be determined from the URL in question. Example of a valid path: 'dumps/keyword/image_01'

    Returns:
        str: The full local path of the image downloaded.
    """

    if 'data:image' in url:
        # separate the metadata from the image data
        head, data = url.split(',', 1)

        # get the file extension (gif, jpeg, png)
        ext = head.split(';')[0].split('/')[1]

        # decode the image data
        plain_data = base64.b64decode(data)

        # write the image to a file
        fpath = str(loc) + '.' + ext

        # save file if it does not exist
        if not os.path.exists(fpath):
            with open(fpath, 'wb') as f:
                f.write(plain_data)
    else:
        path = os.path.basename(urlparse(url).path)
        ext = 'jpg' if len(path.split('.')) == 1 else path.split('.')[-1]
        fpath = str(loc) + '.' + ext

        # save file file it does not exist
        if not os.path.exists(fpath):
            try:
                urllib.request.urlretrieve(url, fpath)
            except Exception as e:
                logging.warn('[download]: %s' % e)
                return None

    return fpath


if __name__ == "__main__":
    logging.info('bot started.')

    # specify keywords and category to look for
    CATEGORY = "cyberpunk"
    keywords = [i.strip().lower() for i in open('keywords.txt') if i.strip()]

    for keyword in keywords:
        logging.info("[keyword]: started '%s' under '%s'" %
                     (keyword, CATEGORY))

        # define paths
        keyword_slug = re.sub(' +', '_', keyword)
        category_slug = re.sub(' +', '_', CATEGORY)
        meta_path = SAVE_ROOT / 'tmp' / \
            category_slug / ('%s.json' % keyword_slug)
        tmp_path = SAVE_ROOT / 'tmp' / category_slug / keyword_slug
        dump_path = SAVE_ROOT / 'dumps' / category_slug / keyword_slug

        # create all required directories
        for d in [tmp_path, dump_path]:
            if not os.path.isdir(d):
                os.makedirs(d)

        # find/load images
        if os.path.exists(meta_path):
            # load images
            images = json.load(open(meta_path))
        else:
            # open selenium and get images
            images = find_images(keyword, CATEGORY)
            with open(meta_path, 'w+') as h:
                json.dump(images, h)

        logging.info('[images] loaded: %s' % len(images))

        good_images = 0

        # iterate over all images and mark as good if image has NO text.
        for i, (thumb_url, ori_url) in enumerate(images):
            thumb_path = tmp_path / ("image_%s" % i)
            ori_path = dump_path / ("image_%s" % i)

            thumb_local = download_image(thumb_url, thumb_path)

            # local thumbnail not found
            if not thumb_local:
                continue

            # check if thumbnail has text
            has_text = detect_text(thumb_local)

            logging.info('[vision] has text: %s, path: %s' %
                         (has_text, thumb_local))

            # go to next image if has text
            if has_text:
                continue

            # download image
            download_image(ori_url, ori_path)
            good_images += 1

        logging.info('[images] good: %s' % good_images)

    logging.info('bot done!')
