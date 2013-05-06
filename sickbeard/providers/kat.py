# Author: Mr_Orange <mr_orange@hotmail.it>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of Sick Beard.
#
# Sick Beard is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Sick Beard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Sick Beard.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import traceback
import urllib, urllib2
import re

import sickbeard
import generic
from sickbeard.common import Quality
from sickbeard.name_parser.parser import NameParser, InvalidNameException
from sickbeard import logger
from sickbeard import tvcache
from sickbeard import helpers
from sickbeard.show_name_helpers import allPossibleShowNames, sanitizeSceneName
from sickbeard.common import Overview 
from sickbeard.exceptions import ex
from sickbeard import encodingKludge as ek

from lib import requests
from bs4 import BeautifulSoup

class KATProvider(generic.TorrentProvider):

    def __init__(self):

        generic.TorrentProvider.__init__(self, "KickAssTorrents")
        
        self.supportsBacklog = True

        self.cache = KATCache(self)
        
        self.url = 'http://katproxy.com/'

        self.searchurl = self.url+'usearch/%s/?field=seeders&sorder=desc'  #order by seed       

    def isEnabled(self):
        return sickbeard.KAT
        
    def imageName(self):
        return 'kat.png'
    
    def getQuality(self, item):
        
        quality = Quality.sceneQuality(item[0])
        return quality    

    def _reverseQuality(self, quality):

        quality_string = ''

        if quality == Quality.SDTV:
            quality_string = 'HDTV x264'
        if quality == Quality.SDDVD:
            quality_string = 'DVDRIP'    
        elif quality == Quality.HDTV:    
            quality_string = '720p HDTV x264'
        elif quality == Quality.FULLHDTV:
            quality_string = '1080p HDTV x264'        
        elif quality == Quality.RAWHDTV:
            quality_string = '1080i HDTV mpeg2'
        elif quality == Quality.HDWEBDL:
            quality_string = '720p WEB-DL h264'
        elif quality == Quality.FULLHDWEBDL:
            quality_string = '1080p WEB-DL h264'            
        elif quality == Quality.HDBLURAY:
            quality_string = '720p Bluray x264'
        elif quality == Quality.FULLHDBLURAY:
            quality_string = '1080p Bluray x264'  
        
        return quality_string

    def _find_season_quality(self,title, torrent_link, ep_number):
        """ Return the modified title of a Season Torrent with the quality found inspecting torrent file list """
        
        mediaExtensions = ['avi', 'mkv', 'wmv', 'divx',
                           'vob', 'dvr-ms', 'wtv', 'ts'
                           'ogv', 'rar', 'zip', 'mp4'] 
        
        quality = Quality.UNKNOWN        
        
        fileName = None

        data = self.getURL(torrent_link)
        
        if not data:
            return None
        
        try: 
            soup = BeautifulSoup(data)
            file_table = soup.find('table', attrs = {'class': 'torrentFileList'})

            if not file_table:
                return None 
            
            files = [x.text for x in file_table.find_all('td', attrs = {'class' : 'torFileName'} )]
            videoFiles = filter(lambda x: x.rpartition(".")[2].lower() in mediaExtensions, files)
            
            #Filtering SingleEpisode/MultiSeason Torrent
            if len(videoFiles) < ep_number or len(videoFiles) > float(ep_number * 1.1 ): 
                logger.log(u"Result " + title + " Seem to be a Single Episode or MultiSeason torrent, skipping result...", logger.DEBUG)
                return None
                
            for fileName in videoFiles:
                quality = Quality.sceneQuality(os.path.basename(fileName))
                if quality != Quality.UNKNOWN: break
    
            if fileName!=None and quality == Quality.UNKNOWN:
                quality = Quality.assumeQuality(os.path.basename(fileName))            
    
            if quality == Quality.UNKNOWN:
                logger.log(u"Unable to obtain a Season Quality for " + title, logger.DEBUG)
                return None
    
            try:
                myParser = NameParser()
                parse_result = myParser.parse(fileName)
            except InvalidNameException:
                return None
            
            logger.log(u"Season quality for "+title+" is "+Quality.qualityStrings[quality], logger.DEBUG)
            
            if parse_result.series_name and parse_result.season_number: 
                title = parse_result.series_name+' S%02d' % int(parse_result.season_number)+' '+self._reverseQuality(fileName, quality)
            
            return title
            
        except Exception, e:
            logger.log(u"Failed parsing " + self.name + (" Exceptions: "  + str(e) if e else ''), logger.ERROR)
                

    def _get_season_search_strings(self, show, season=None):

        search_string = {'Episode': []}
    
        if not show:
            return []

        seasonEp = show.getAllEpisodes(season)

        wantedEp = [x for x in seasonEp if show.getOverview(x.status) in (Overview.WANTED, Overview.QUAL)]          

        #If Every episode in Season is a wanted Episode then search for Season first
        if wantedEp == seasonEp and not show.air_by_date:
            search_string = {'Season': [], 'Episode': []}
            for show_name in set(allPossibleShowNames(show)):
                ep_string = show_name +' S%02d' % int(season) + ' -S%02d' % int(season) + 'E' + ' category:tv' #1) ShowName SXX -SXXE  
                search_string['Season'].append(ep_string)
                      
                ep_string = show_name+' Season '+str(season)+' -Ep*' + ' category:tv' #2) ShowName Season X  
                search_string['Season'].append(ep_string)

        #Building the search string with the episodes we need         
        for ep_obj in wantedEp:
            search_string['Episode'] += self._get_episode_search_strings(ep_obj)[0]['Episode']
        
        #If no Episode is needed then return an empty list
        if not search_string['Episode']:
            return []
        
        return [search_string]

    def _get_episode_search_strings(self, ep_obj):
       
        search_string = {'Episode': []}
       
        if not ep_obj:
            return []
                
        if ep_obj.show.air_by_date:
            for show_name in set(allPossibleShowNames(ep_obj.show)):
                ep_string = sanitizeSceneName(show_name) +' '+ str(ep_obj.airdate)
                search_string['Episode'].append(ep_string)
        else:
            for show_name in set(allPossibleShowNames(ep_obj.show)):
                ep_string = sanitizeSceneName(show_name) +' '+ \
                sickbeard.config.naming_ep_type[2] % {'seasonnumber': ep_obj.season, 'episodenumber': ep_obj.episode} +'|'+\
                sickbeard.config.naming_ep_type[0] % {'seasonnumber': ep_obj.season, 'episodenumber': ep_obj.episode} +'|'+\
                sickbeard.config.naming_ep_type[3] % {'seasonnumber': ep_obj.season, 'episodenumber': ep_obj.episode} + ' category:tv' \

                search_string['Episode'].append(ep_string)
    
        return [search_string]

    def _doSearch(self, search_params, show=None):

        results = []
        items = {'Season': [], 'Episode': [], 'RSS': []}

        for mode in search_params.keys():
            for search_string in search_params[mode]:
                
                if mode != 'RSS':
                    searchURL = self.searchurl %(urllib.quote(search_string))    
                    logger.log(u"Search string: " + searchURL, logger.DEBUG)
                else:
                    searchURL = self.url + 'tv/?field=time_add&sorder=desc'
                    logger.log(u"KAT cache update URL: "+ searchURL, logger.DEBUG)
                    
                html = self.getURL(searchURL)
                if not html:
                    continue

                try:
                    soup = BeautifulSoup(html)

                    torrent_table = soup.find('table', attrs = {'class' : 'data'})
                    torrent_rows = torrent_table.find_all('tr')[1:] if torrent_table else None

                    if not torrent_rows:
#                        logger.log(u"The Data returned from " + self.name + " do not contains any torrent", logger.ERROR)
                        continue
                    
                    for tr in torrent_rows:
                        link = self.url + (tr.find('div', {'class': 'torrentname'}).find_all('a')[1])['href']
                        id = tr.get('id')[-7:]
                        title = (tr.find('div', {'class': 'torrentname'}).find_all('a')[1]).text
                        url = tr.find('a', 'imagnet')['href']
                        verified = True if tr.find('a', 'iverify') else False
                        trusted =  True if tr.find('img', {'alt': 'verified'}) else False
                        seeders = int(tr.find_all('td')[-2].text)
                        leechers = int(tr.find_all('td')[-1].text)

                        if mode != 'RSS' and seeders == 0:
                            continue 
                  
                        if sickbeard.KAT_VERIFIED and not verified:
                            logger.log(u"KAT Provider found result "+title+" but that doesn't seem like a verified result so I'm ignoring it",logger.DEBUG)
                            continue

                        if mode == 'Season' and Quality.sceneQuality(title) == Quality.UNKNOWN:
                            ep_number = int(len(search_params['Episode']) / len(allPossibleShowNames(show)))
                            title = self._find_season_quality(title, link, ep_number)

                        if not title:
                            continue

                        item = title, url, id, seeders, leechers

                        items[mode].append(item)

                except Exception, e:
                    logger.log(u"Failed to parsing " + self.name + (" Exceptions: "  + str(e) if e else ''), logger.ERROR)

            #For each search mode sort all the items by seeders
            items[mode].sort(key=lambda tup: tup[3], reverse=True)        

            results += items[mode]  
                
        return results

    def _get_title_and_url(self, item):
        
        title, url, id, seeders, leechers = item
        
        if url:
            url = url.replace('&amp;','&')

        return (title, url)

    def getURL(self, url, headers=None):

        try:
            r = requests.get(url)
        except Exception, e:
            logger.log(u"Error loading "+self.name+" URL: " + str(sys.exc_info()) + " - " + ex(e), logger.ERROR)
            return None
    
        return r.content

    def downloadResult(self, result):
        """
        Save the result to disk.
        """
        
        torrent_hash = re.findall('urn:btih:([\w]{32,40})', result.url)[0].upper()
        
        if not torrent_hash:
           logger.log("Unable to extract torrent hash from link: " + ex(result.url), logger.ERROR) 
           return False
           
        try:
            r = requests.get('http://torcache.net/torrent/' + torrent_hash + '.torrent')
        except Exception, e:
            logger.log("Unable to connect to Torcache: " + ex(e), logger.ERROR)
            return False
                         
        if not r.status_code == 200:
            return False
            
        magnetFileName = ek.ek(os.path.join, sickbeard.TORRENT_DIR, helpers.sanitizeFileName(result.name) + '.' + self.providerType)
        magnetFileContent = r.content

        try:    
            fileOut = open(magnetFileName, 'wb')
            fileOut.write(magnetFileContent)
            fileOut.close()
            helpers.chmodAsParent(magnetFileName)
        except IOError, e:
            logger.log("Unable to save the file: " + ex(e), logger.ERROR)
            return False
        logger.log(u"Saved magnet link to " + magnetFileName + " ", logger.MESSAGE)
        return True

class KATCache(tvcache.TVCache):

    def __init__(self, provider):

        tvcache.TVCache.__init__(self, provider)

        # only poll ThePirateBay every 10 minutes max
        self.minTime = 20

    def updateCache(self):

        if not self.shouldUpdate():
            return

        search_params = {'RSS': ['rss']}
        rss_results = self.provider._doSearch(search_params)
        
        if rss_results:
            self.setLastUpdate()
        else:
            return []
        
        logger.log(u"Clearing " + self.provider.name + " cache and updating with new information")
        self._clearCache()

        for result in rss_results:
            item = (result[0], result[1])
            self._parseItem(item)

    def _parseItem(self, item):

        (title, url) = item

        if not title or not url:
            return

        logger.log(u"Adding item to cache: "+title, logger.DEBUG)

        self._addCacheEntry(title, url)
    
provider = KATProvider()
