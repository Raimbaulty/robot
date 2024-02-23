# -*- coding: utf-8 -*-

import os
import logging
import re
import time
import urllib
import json
import requests
import subprocess
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from queue import Empty
from threading import Thread
from job_mgmt import Job
from datetime import datetime
from base.func_chengyu import cy
from base.func_news import News
from base.func_weather import Weather
from base.weather import get_weather

from constants import ChatType
from wcferry import Wcf, WxMsg
from configuration import Config
from base.func_chatglm import ChatGLM
from base.func_chatgpt import ChatGPT
from base.func_chatnio import Chatnio
from base.func_tigerbot import TigerBot
from base.func_xinghuo_web import XinghuoWeb


class Robot(Job):
    """个性化自己的机器人
    """

    def __init__(self, config: Config, wcf: Wcf, chat_type: int) -> None:
        self.wcf = wcf
        self.config = config
        self.LOG = logging.getLogger("Robot")
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
        self.song_list = {}
        self.file_path = ""
        self.voice_path = ""
        self.douyin_hotlist = {}
        self.douyin_downloadlink = {}
        self.commands = {
            "画": self.handle_画, "翻译": self.handle_翻译,  "拼音": self.handle_拼音,
            "搜歌": self.handle_搜歌, "听歌": self.handle_听歌, "签名": self.handle_签名,
            "网名": self.handle_网名, "取名": self.handle_取名, "典故": self.handle_典故,
            "重名": self.handle_重名,  "搜题": self.handle_搜题, "台词": self.handle_台词,
            "扮演": self.handle_扮演, "摸鱼": self.handle_摸鱼,
            "举牌": self.handle_举牌, "云图": self.handle_云图, "识图": self.handle_识图,
            "查榜": self.handle_查榜, "不可说": self.handle_不可说, "头像": self.handle_头像,
            "到账": self.handle_到账, "追番": self.handle_追番, "抖音": self.handle_抖音,
            "搜抖音": self.handle_搜抖音, "看抖音": self.handle_看抖音, "刷抖音": self.handle_刷抖音,
            "小姐姐": self.handle_小姐姐, "百家姓": self.handle_百家姓, "发证书": self.handle_发证书,
            "卡路里": self.handle_卡路里, "查星座": self.handle_查星座, "查油价": self.handle_查油价,
            "查号码": self.handle_查号码, "查天气": self.handle_查天气, "查功能": self.handle_查功能,
            "讲述人": self.handle_讲述人,
        }

        if ChatType.is_in_chat_types(chat_type):
            if chat_type == ChatType.TIGER_BOT.value and TigerBot.value_check(self.config.TIGERBOT):
                self.chat = TigerBot(self.config.TIGERBOT)
            elif chat_type == ChatType.CHATGPT.value and ChatGPT.value_check(self.config.CHATGPT):
                self.chat = ChatGPT(self.config.CHATGPT)
            elif chat_type == ChatType.XINGHUO_WEB.value and XinghuoWeb.value_check(self.config.XINGHUO_WEB):
                self.chat = XinghuoWeb(self.config.XINGHUO_WEB)
            elif chat_type == ChatType.CHATGLM.value and ChatGLM.value_check(self.config.CHATGLM):
                self.chat = ChatGLM(self.config.CHATGLM)
            elif chat_type == ChatType.CHATNIO.value and Chatnio.value_check(self.config.CHATNIO):
                self.chat = Chatnio(self.config.CHATNIO)    
            else:
                self.LOG.warning("未配置模型")
                self.chat = None
        else:
            if TigerBot.value_check(self.config.TIGERBOT):
                self.chat = TigerBot(self.config.TIGERBOT)
            elif ChatGPT.value_check(self.config.CHATGPT):
                self.chat = ChatGPT(self.config.CHATGPT)
            elif XinghuoWeb.value_check(self.config.XINGHUO_WEB):
                self.chat = XinghuoWeb(self.config.XINGHUO_WEB)
            elif ChatGLM.value_check(self.config.CHATGLM):
                self.chat = ChatGLM(self.config.CHATGLM)
            elif Chatnio.value_check(self.config.CHATNIO):
                self.chat = Chatnio(self.config.CHATNIO)    
            else:
                self.LOG.warning("未配置模型")
                self.chat = None

    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False

    def add_receiver_info(function):
        #给要发送的消息添加地址和类型
        def wrapper(self, msg):
            try:
                rsp = function(self, msg)
                if rsp:
                    receiver_id = msg.roomid if msg.roomid else msg.sender
                    group_id = msg.sender if msg.roomid else None
                    msg_type = self.classify_msg_type(rsp) 
                    msg_dict = {
                        "receiver_id": receiver_id,
                        "group_id": group_id,
                        "msg_type": msg_type,
                        "content": rsp,
                    }
                    return self.sendMsg(msg_dict)
                else:
                    return None
            except Exception as e:
                self.LOG.error(e)
                return None

        return wrapper

    def classify_msg_type(self, content) -> str:
        #判断发送消息的类型
        if os.path.isfile(content) or content.startswith("http"):
            if content.lower().endswith(('.jpg', '.jpeg', '.png')):
                return "image"
            if content.lower().endswith(('.amr')):
                return "voice"
            else:
                return "file"
        else:
            return "text"

    def sendMsg(self, msg_dict: dict) -> None:
        """ 发送消息
        :param msg_dict: 包含消息相关信息的字典
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        msg = msg_dict["content"]
        msg_type = msg_dict["msg_type"]
        receiver = msg_dict["receiver_id"]
        at_list = msg_dict["group_id"]

        # msg 中需要有 @ 名单中一样数量的 @
        ats = ""
        if at_list:
            if at_list == "notify@all":  # @所有人
                ats = " @所有人"
            else:
                wxids = at_list.split(",")
                for wxid in wxids:
                    # 根据 wxid 查找群昵称
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid, receiver)}"

        # 对于文本消息，包含 ats（如果有的话）
        if msg_type == "text":
            message = f"{ats}\n{msg}" if ats else f"{msg}"
            self.LOG.info(f"To {receiver}: {message}")
            self.wcf.send_text(message, receiver, at_list)
        elif msg_type == "image":
            # 对于图片消息，只发送图片路径或URL
            self.LOG.info(f"To {receiver}: Sending image.")
            self.wcf.send_image(msg, receiver)
        elif msg_type == "amr":
            # 对于语音消息，只发送语音路径或URL
            self.LOG.info(f"To {receiver}: Sending voice.")
            self.wcf.send_file(msg, receiver)
        else:
            # 对于文件消息，只发送文件路径或URL
            self.LOG.info(f"To {receiver}: Sending file.")
            self.wcf.send_file(msg, receiver)
        # ... 其他消息类型的处理 ...

    def toAt(self, msg: WxMsg) -> bool:
        """处理被 @ 消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        msg.content = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
        for cmd, handler in self.commands.items():
            if msg.content.strip().startswith(cmd):
                handler(msg)
                break  # 结束循环
        else:
            return self.toChitchat(msg)

    @add_receiver_info
    def toChengyu(self, msg: WxMsg) -> bool:
        """
        处理成语查询/接龙消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        status = False
        texts = re.findall(r"^([#|?|？])(.*)$", msg.content)
        # [('#', '天天向上')]
        if texts:
            flag = texts[0][0]
            text = texts[0][1]
            if flag == "#":  # 接龙
                if cy.isChengyu(text):
                    rsp = cy.getNext(text)
                    if rsp:
                        return rsp
                        status = True
            elif flag in ["?", "？"]:  # 查词
                if cy.isChengyu(text):
                    rsp = cy.getMeaning(text)
                    if rsp:
                        return rsp
                        status = True

        return status

    @add_receiver_info
    def toChitchat(self, msg: WxMsg) -> str:
        """闲聊，接入 ChatGPT
        """
        if not self.chat:  # 没接 ChatGPT，固定回复
            rsp = "你@我干嘛？"
        else:  # 接了 ChatGPT，智能回复
            msg.content = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
            rsp = self.chat.get_answer(msg.content, (msg.roomid if msg.from_group() else msg.sender)).split('####')[0]  #用split删除广告消息

        if rsp:
            return rsp
        else:
            self.LOG.error(f"无法从 ChatGPT 获得答案")
            return None

    def processMsg(self, msg: WxMsg) -> None:
        if msg.from_group():
            if msg.roomid not in self.config.GROUPS:
                return
            if msg.is_at(self.wxid):  # 被@
                self.toAt(msg)           
            
            if msg.type == 3:  # 图片消息
                img_path = r"C:/Users/Raimbault/Documents/WeChat Files/wxid_55zyiv0rij9a12/FileStorage/MsgAttach/f2332fbf6604994906debc30e386a18a/Image/2023-12/"
                self.file_path = self.wcf.download_image(msg.id, msg.extra, img_path, 5)
                print(f"Image download successfully")

            # if msg.type == 34:  # 语音信息
            #     dir_path = r"C:\Users\Raimbault\Documents\WeChat Files\wxid_55zyiv0rij9a12\FileStorage\File\2023-12"                
            #     self.voice_path = self.wcf.get_audio_msg(msg.id, dir_path, 3)
            #     print(f"Audio download successfully")
            #     text = self.stt()
            #     print(text)
            #     rsp = self.chat.get_answer(text, msg.roomid).split('####')[0]  #用split删除广告消息
            #     print(rsp)
            #     speech = self.tts(rsp).replace("\n", "")
            #     print(speech)
            #     self.wcf.send_file(speech, msg.roomid)

            else: # 其他消息    
                self.toChengyu(msg)
            return #不返回会触发chitchat
        #return #取消注释拒绝接收私聊 
        else:
            # 非群聊信息，按消息类型进行处理        
            
            # if msg.type == 37:  # 好友请求
            #     self.autoAcceptFriendRequest(msg)

            if msg.type == 3:  # 图片消息
                dir_path = r"C:/Users/Raimbault/Documents/WeChat Files/wxid_55zyiv0rij9a12/FileStorage/MsgAttach/f2332fbf6604994906debc30e386a18a/Image/2023-12/"
                self.file_path = self.wcf.download_image(msg.id, msg.extra, dir_path,5)
                print(f"图片下载成功")

            if msg.type == 34:  # 语音信息
                dir_path = r"C:\Users\Raimbault\Documents\WeChat Files\wxid_55zyiv0rij9a12\FileStorage\File\2023-12"                
                self.voice_path = self.wcf.get_audio_msg(msg.id, dir_path, 3)
                print(f"语音下载成功")
                text = self.stt()
                print(text)
                rsp = self.chat.get_answer(text, msg.sender).split('####')[0]  #用split删除广告消息
                print(rsp)
                speech = self.tts(rsp).replace("\n", "")
                print(speech)
                self.wcf.send_file(speech, msg.sender)

            # if msg.type == 43:  # 视频信息
            #     dir_path = r"C:/Users/Raimbault/Documents/WeChat Files/wxid_55zyiv0rij9a12/FileStorage/Video/2023-12/"
            #     self.file_path = self.wcf.download_image(msg.id, msg.extra, dir_path, 60)             
            #     print("视频下载成功")


            if msg.type == 10000:  # 系统信息
                self.sayHiToNewFriend(msg)

            elif msg.type == 0x01:  # 文本消息
                # 让配置加载更灵活，自己可以更新配置。也可以利用定时任务更新。
                if msg.from_self():
                    if msg.content == "/更新":
                        self.config.reload()
                        self.LOG.info("已更新")       
                else: 
                    # 如果是天气，就重发天气预报
                    if msg.content == "/天气":
                        self.weatherReport()
                    # 如果是新闻，就重发隔夜要闻
                    elif msg.content == "/新闻":
                        self.newsReport()                
                    else:  # 其他消息
                        for cmd, handler in self.commands.items():
                            if msg.content.strip().startswith(cmd):
                                handler(msg)
                                break  # 结束循环
                        else:
                            self.toChitchat(msg)  # 闲聊

    def onMsg(self, msg: WxMsg) -> int:
        try:
            self.LOG.info(msg)  # 打印信息
            self.processMsg(msg)
        except Exception as e:
            self.LOG.error(e)

        return 0

    def enableRecvMsg(self) -> None:
        self.wcf.enable_receiving_msg(self.onMsg)

    def enableReceivingMsg(self) -> None:
        def innerProcessMsg(wcf: Wcf):
            while wcf.is_receiving_msg():
                try:
                    msg = wcf.get_msg()
                    self.LOG.info(msg)
                    self.processMsg(msg)
                except Empty:
                    continue  # Empty message
                except Exception as e:
                    self.LOG.error(f"Receiving message error: {e}")

        self.wcf.enable_receiving_msg()
        Thread(target=innerProcessMsg, name="GetMessage", args=(self.wcf,), daemon=True).start()

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """ 发送消息
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        # msg 中需要有 @ 名单中一样数量的 @
        ats = ""
        if at_list:
            if at_list == "notify@all":  # @所有人
                ats = " @所有人"
            else:
                wxids = at_list.split(",")
                for wxid in wxids:
                    # 根据 wxid 查找群昵称
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid, receiver)}"

        # {msg}{ats} 表示要发送的消息内容后面紧跟@，例如 北京天气情况为：xxx @张三
        if ats == "":
            self.LOG.info(f"To {receiver}: {msg}")
            self.wcf.send_text(f"{msg}", receiver, at_list)
        else:
            self.LOG.info(f"To {receiver}: {ats}\r{msg}")
            self.wcf.send_text(f"{ats}  {msg}", receiver, at_list)

    def getAllContacts(self) -> dict:
        """
        获取联系人（包括好友、公众号、服务号、群成员……）
        格式: {"wxid": "NickName"}
        """
        contacts = self.wcf.query_sql("MicroMsg.db", "SELECT UserName, NickName FROM Contact;")
        return {contact["UserName"]: contact["NickName"] for contact in contacts}

    def keepRunningAndBlockProcess(self) -> None:
        """
        保持机器人运行，不让进程退出
        """
        while True:
            self.runPendingJobs()
            time.sleep(1)

    def autoAcceptFriendRequest(self, msg: WxMsg) -> None:
        try:
            xml = ET.fromstring(msg.content)
            v3 = xml.attrib["encryptusername"]
            v4 = xml.attrib["ticket"]
            scene = int(xml.attrib["scene"])
            self.wcf.accept_new_friend(v3, v4, scene)

        except Exception as e:
            self.LOG.error(f"同意好友出错：{e}")

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(f"Hi {nickName[0]}，我自动通过了你的好友请求。", msg.sender)

    def newsReport(self) -> None:
        receivers = self.config.NEWS
        if not receivers:
            return

        news = News().get_important_news()
        for r in receivers:
            self.sendTextMsg(news, r)

    def weatherReport(self) -> None:
        receivers = self.config.WEATHER
        if not receivers:
            return

        weather = Weather().get_weather()
        for r in receivers:
            self.sendTextMsg(weather, r)

    def tts(self, msg): #原神版
        # 根据文字生成原神语音
        speaker = "八重神子" #speaker_dict = {1: "空", 2: "荧", 3: "派蒙", 4: "纳西妲", 5: "阿贝多", 6: "温迪", 7: "枫原万叶", 8: "钟离", 9: "荒泷一斗", 10: "八重神子", 11: "艾尔海森", 12: "提纳里", 13: "迪希雅", 14: "卡维", 15: "宵宫", 16: "莱依拉", 17: "赛诺", 18: "诺艾尔", 19: "托马", 20: "凝光", 21: "莫娜"}
        types = None # 等于2输出音频 
        noise = 0.6  # 控制感情变化程度，默认为0.6
        noisew = 0.8 #控制音节发音长度变化程度，默认为0.8
        sdp = 0.4    #Duration Predictor中SDP的占比，此值越大则语气波动越强烈，但可能偶发出现语调奇怪。
        Length = 1   #默认为1                    
        params = {'msg':msg, 'speaker':speaker, 'type':types, 'noise':noise, 'noisew':noisew, 'sdp':sdp, 'Length':Length}
        response = requests.get('https://api.lolimi.cn/API/yyhc/y.php', params = params)
        # 解析响应为 JSON
        data = json.loads(response.text)
        # 获取下载 URL
        download_url = data.get('music')
        # 发送 GET 请求
        response = requests.get(download_url, stream=True)
        # 检查响应状态码
        if response.status_code == 200:
            # 将响应的内容写入到文件
            with open(r'C:\Users\Raimbault\WeChatRobot-39.0.5.0\audio.wav', 'wb') as f:
                f.write(response.content)
            print('Audio generates successfully')
            rsp = r"C:\Users\Raimbault\WeChatRobot-39.0.5.0\audio.wav"
            return rsp
        else:
            return None
            print('Failed to generate audio')    

    def stt(self):
        #语音转文字
        url = "https://api.pearktrue.cn/api/audiocr/"
        file_path = self.voice_path
        try:
            with open(file_path, "rb") as file:
                formdata = {"file": file}
                response = requests.post(url, files=formdata)
            if response.status_code == 200:
                data = response.json()
                rsp = data.get("data", {}).get("content", "Not found")
            else:
                rsp = None
        except Exception as e:
            print(f"Error processing STT request: {e}")
            rsp = None
        return rsp


    @add_receiver_info
    def handle_画(self, msg) -> None:
        # 调用StableDiffusion绘画，格式：画 一只会飞的猪
        content = msg.content.replace('画', "").strip()
        if not content:
            return f"1.功能介绍：\nStableDiffusion绘画\n2.调用格式：\n画一只会飞的猪"        
        mode = 'vertical' # 模式：正方形normal、竖版vertical、横版horizontal
        prompt = content
        params = {'mode':mode, 'prompt':prompt}         
        response = requests.get('https://api.pearktrue.cn/api/stablediffusion', params = params)
        if response.status_code == 200:
            data = json.loads(response.text)
            rsp = data.get('imgurl', 'Not found')
        else:
            rsp = None
        return rsp

    @add_receiver_info
    def handle_翻译(self, msg):
        # 调用谷歌翻译，中英互译
        content = msg.content.replace("翻译", "").strip()
        if not content:
            return f"1.功能介绍：\n谷歌翻译，支持中英互译\n2.调用格式：\n翻译我喜欢你"
        types = "auto" # 翻译模式(auto=自动检测[默认]，en=英文转中文，zh=中文转英文)
        text = content
        params = {"type":types, "text":text}
        response = requests.get("https://api.pearktrue.cn/api/googletranslate", params = params)
        if response.status_code == 200:
            data = json.loads(response.text)
            result = data.get("result", "Not found")
            rsp = result
        else:
            rsp = None
        return rsp

    @add_receiver_info
    def handle_拼音(self, msg):
        # 输出汉字的拼音
        content = msg.content.replace("拼音", "").strip()
        if not content:
            return f"1.功能介绍：\n查找汉字拼音\n2.调用格式：\n拼音我爱你" 
        word = content
        params = {"word":word}
        print(params)
        response = requests.get("https://api.pearktrue.cn/api/word/pinyin", params = params)
        if response.status_code == 200:
            data = json.loads(response.text)
            print(data)
            pinyin_list = data.get("data", "Not found")
            rsp = ' '.join(pinyin_list)
        else:
            rsp = None
        return rsp

    @add_receiver_info
    def handle_搜歌(self, msg):
        # 聚合音乐解析
        content = msg.content.replace("搜歌", "").strip()
        if not content:
            return f"1.功能介绍：\n搜索歌曲并将序号传给【听歌】\n2.调用格式：\n搜歌周杰伦" 
        name = content
        params = {"name":name}
        response = requests.get("https://api.pearktrue.cn/api/music/wanneng.php", params = params)
        if response.status_code == 200:
            data = json.loads(response.text)
            if "data" in data:
                songs = data["data"]
                output = f'我为您找到了以下结果：\n'
                
                for i, song in enumerate(songs):
                    if i >= 10:  # 只显示10个结果
                        break
                    self.song_list[i+1] = f"https://api.pearktrue.cn/api/music/wanneng.php?name={name}&num={song['id']}"
                    print(self.song_list)
                    output += f'Top -{song["id"]}-\n'
                    output += f'歌曲名: {song["song_name"]}\n'
                    output += f'歌手: {song["singer"]}\n'
                    output += f'--------------------------------\n'
                output += f'请输入“听歌+数字”来播放音乐\n'
                rsp = output               
            else:
                rsp = None
        return rsp

    @add_receiver_info
    def handle_听歌(self, msg):
        # 聚合音乐解析
        content = msg.content.replace('听歌', "").strip()
        if not content:
            return f"1.功能介绍：\n通过【搜歌】序号或名字听歌\n调用格式\n格式1：听歌1\n格式2：听歌倒带"
        if content.isdigit():
            rank = int(content)
            if rank in self.song_list:
                url = self.song_list[rank]
            else:
                return "请先调用【搜歌】，若已搜歌请检查序号"
        else:
            url = "https://api.pearktrue.cn/api/music/wanneng.php?num=1&name="+ content
        print(url)         
        response = requests.get(url)
        if response.status_code == 200:
            data = json.loads(response.text)            
            rsp = data.get("data", {}).get("music_link", "Not found")
        else:
            rsp = None
        return rsp

    @add_receiver_info
    def handle_签名(self, msg):
        # 生成个性签名图片,最多支持三个字
        content = msg.content.replace('签名', "").strip()
        if not content:
            return f"1.功能介绍：\n生成个性签名，支持: hsq花式签 swq商务签 gxq个性牵 sxlbz手写连笔字 zkt正楷体 wrns温柔女生 xsq潇洒牵 cjysq超级艺术签 xsq行书签 ksq楷书牵 qsq情书签 xcq行草签 ktkaq卡通可爱签\n2.调用格式：\n签名hsq，郭富城"
        style, word = content.split("，") # style支持: hsq花式签 swq 商务签 gxq 个性牵 sxlbz 手写连笔字 zkt 正楷体 wrns 温柔女生 xsq 潇洒牵 cjysq 超级艺术签 xsq 行书签 ksq 楷书牵 qsq 情书签 xcq 行草签 ktkaq 卡通可爱签
        size = 80             # 字体大小
        fontcolor = "#000000" # 字体颜色
        colors = "#ffffff"    # 背景颜色
        params = {'word': word, "type":style, "size":size, "fontcolor":fontcolor, "colors":colors}
        response = requests.get('https://api.pearktrue.cn/api/signature', params=params)
        if response.status_code == 200:
            # 以二进制写模式（binary write mode）打开文件
            with open(r'C:\Users\Raimbault\output_image.png', 'wb') as f:
                # 将响应内容写入文件
                f.write(response.content)
            print("图片下载成功")                            
            rsp = r"C:\Users\Raimbault\output_image.png"
            return rsp
        else:
            return None
            print("图片下载失败")

    @add_receiver_info
    def handle_网名(self, msg):
        # 根据姓氏取网名
        content = msg.content.replace('网名', "").strip()
        if not content:
            return f"1.功能介绍：\n根据姓氏取网名\n2.调用格式：\n网名刘"
        name = content
        params = {'name': name}
        response = requests.get('https://api.pearktrue.cn/api/namexy', params=params)
        if response.status_code == 200:
            data = response.json()
            name_list = data['data']
            rsp = "\n".join(f"{i}.{name}" for i, name in enumerate(name_list, 1))
            print("取名成功")
            return rsp
        else:
            return None
            print("取名失败")

    @add_receiver_info
    def handle_取名(self, msg):
        # 取名，默认设置输出10个，对应count=9
        content = msg.content.replace('取名', "").strip()
        if not content:
            return f"1.功能介绍：\n根据姓氏取真名\n2.调用格式：\n取名王"
        xing = content
        male_params = {'xing': xing, 'sex': 'male', 'count': 9}
        female_params = {'xing': xing, 'sex': 'female', 'count': 9}        
        male_response = requests.get('https://api.pearktrue.cn/api/name/generate', params=male_params)
        female_response = requests.get('https://api.pearktrue.cn/api/name/generate', params=female_params)        
        if male_response.status_code == 200 and female_response.status_code == 200:
            male_data = male_response.json()['data']
            female_data = female_response.json()['data']            
            male_names = "\n".join(f"{i}.{name}" for i, name in enumerate(male_data, 1))
            female_names = "\n".join(f"{i}.{name}" for i, name in enumerate(female_data, 1))            
            print("取名成功")
            return f"如果是男孩: \n{male_names}\n\n如果是女孩: \n{female_names}"
        else:
            print("取名失败")
            return None

    @add_receiver_info
    def handle_重名(self, msg):
        # 查询重名
        content = msg.content.replace('重名', "").strip()
        if not content:
            return f"1.功能介绍：\n查询重名\n2.调用格式：\n重名张三"
        name = content
        response = requests.get('https://api.pearktrue.cn/api/name/check.php?name='+ name)
        if response.status_code == 200:
            data = json.loads(response.text)
            info = data['data']
            output = ""
            output += f"查询成功：\n"
            output += f"查询姓名: {info['name']}\n"
            output += f"统计人数: {info['count']}\n"
            output += f"男性占比: {info['male']}\n"
            output += f"女性占比: {info['female']}\n"
            rsp = output
            return rsp
            print("查询成功")
        else:
            return None
            print("查询失败")

    @add_receiver_info
    def handle_典故(self, msg):
        # 根据意思搜索现代文和古诗文
        content = msg.content.replace('典故', "").strip()
        if not content:
            return f"1.功能介绍：\n根据语意查典故\n2.调用格式：\n典故遇到困难不要怕"
        modern_params = {"mean": content, "type": "现代文"}
        ancient_params = {"mean": content, "type": "古诗文"}
        modern_response = requests.get('https://api.pearktrue.cn/api/meansearch', params=modern_params)
        ancient_response = requests.get('https://api.pearktrue.cn/api/meansearch', params=ancient_params)
        if modern_response.status_code == 200 and ancient_response.status_code == 200:
            modern_data = modern_response.json()
            print(modern_data)
            ancient_data = ancient_response.json()
            print(ancient_data)
            modern_items = modern_data.get('data', [])
            ancient_items = ancient_data.get('data', [])
            lines = ["【现代文】："] + \
                     [f"<{i}>.{item['quote']}\n出自: {item['source']}\n--------------------------------" for i, item in enumerate(modern_items[:10], 1)] + \
                     ["【古诗文】："] + \
                     [f"<{i}>.{item['quote']}\n出自: {item['source']}\n--------------------------------" for i, item in enumerate(ancient_items[:10], 1)]
            rsp = '\n'.join(lines)
            print("典故查询成功")
            return rsp
        else:
            return None
            print("典故查询失败")

    @add_receiver_info
    def handle_台词(self, msg):
        # 根据句子查电影台词
        page = 1
        content = msg.content.replace('台词', "").strip()
        if not content:
            return f"1.功能介绍：\n根据台词查找电影\n2.调用格式：\n格式1：台词我爱你\n格式2：台词3我爱你\n注：3表示第3页，默认第1页"
        if content[0].isdigit():
            # 如果是数字，提取页码
            page_end_index = 1
            while page_end_index < len(content) and content[page_end_index].isdigit():
                page_end_index += 1
            page = int(content[:page_end_index])
            word = content[page_end_index:]
        else:
            # 如果不是数字，整个内容都是台词
            word = content         
        params = {"word": word, "page": page}
        response = requests.get('https://api.pearktrue.cn/api/media/lines.php', params=params)

        if response.status_code == 200:
            try:
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    output = "为您找到以下结果：\n"
                    project_count = 1
                    for item in data["data"]:
                        output += f'{project_count}. {item["title"]}\n'
                        zh_lines = '\n'.join([f'“{line}”' for line in item.get("all_zh_word", [])])
                        en_lines = '\n'.join([f'“{line}”' for line in item.get("all_en_word", [])])
                        output += f'{zh_lines}\n'
                        output += '-' * 32 + '\n'  # 分割线
                        output += f'{en_lines}\n\n'
                        project_count += 1
                    return output
                else:
                    return "没有找到相关的电影台词。"
            except Exception as e:
                print(f"Error processing data: {e}")
                return "处理数据时发生错误。"   

    @add_receiver_info
    def handle_扮演(self, msg):
        #随机发送一条语音，支持扮演怼人、绿茶、御姐
        content = msg.content.replace('扮演', "").strip()
        if not content:
            return f"1.功能介绍：\n扮演角色，支持扮演怼人、绿茶、御姐\n2.调用格式：\n扮演御姐"
        role = content
        role_dict = {"怼人": 'duiren/', "绿茶": 'greentea/', '御姐':'yujie/'}
        base_url = "https://api.pearktrue.cn/api/" + role_dict[role]
        response = requests.get(base_url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            video = soup.find('video')
            source = video.find('source')
            relative_url = source.get('src')
            mp3_url = urllib.parse.urljoin(base_url, relative_url)
            response = requests.get(mp3_url, stream=True)
            with open(r'C:\Users\Raimbault\WeChatRobot-39.0.5.0\audio.mp3', 'wb') as file:
                file.write(response.content)     
            print("Generate audio successfully.")
            rsp = r'C:\Users\Raimbault\WeChatRobot-39.0.5.0\audio.mp3'
        else:
            rsp = None
            print("Failed to generate")
        return rsp

    @add_receiver_info
    def handle_摸鱼(self, msg):
        #生成摸鱼日历
        response = requests.get('https://api.vvhan.com/api/moyu')
        if response.status_code == 200:
            # 以二进制写模式（binary write mode）打开文件
            with open(r'C:\Users\Raimbault\output_image.jpg', 'wb') as f:
                # 将响应内容写入文件
                f.write(response.content)            
            rsp = r"C:\Users\Raimbault\output_image.jpg"
            return rsp
            print("摸鱼日历下载成功")
        else:
            return None
            print("摸鱼日历下载失败")

    @add_receiver_info
    def handle_举牌(self, msg):
        # 将文字转化为举牌图片
        content = msg.content.replace('举牌', "").strip()
        if not content:
            return f"1.功能介绍：\n小人举牌\n2.调用格式：\n举牌我出1个亿" 
        params = {"msg":content}
        response = requests.get('https://api.cenguigui.cn/api/jp', params = params)
        if response.status_code == 200:
            # 以二进制写模式（binary write mode）打开文件
            with open(r'C:\Users\Raimbault\output_image.jpg', 'wb') as f:
                # 将响应内容写入文件
                f.write(response.content)
            print("图片下载成功")                            
            rsp = r"C:\Users\Raimbault\output_image.jpg"
            return rsp
        else:
            return None
            print("图片下载失败")

    @add_receiver_info
    def handle_云图(self, msg):
        # 根据文本生成中国行政区划的云图
        content = msg.content.replace('云图', "").strip()
        if not content:
            return f"1.功能介绍：\n根据长文本生成中国地图的云图\n2.调用格式：\n云图苹果, 香蕉, 樱桃, 枣, 接骨木果, 无花果, 西柚, 哈密瓜, 猕猴桃, 柠檬, 芒果, 油桃, 橙子, 番木瓜, 山楂, 草莓, 橙子, 柑橘, 葡萄, 西瓜, 杏子, 黑莓, 椰子, 火龙果, 芭乐, 猕猴桃, 青柠, 甜瓜, 桃子, 李子, 葡萄, 蓝莓, 菠萝, 石榴, 梨子, 柿子, 青柠, 荔枝, 蔓越莓, 香瓜, 黑醋栗, 百香果, 石榴, 草莓, 黑醋栗, 醋栗, 青提"
        params = {"text":content}
        response = requests.get("https://api.pearktrue.cn/api/wordcloud", params = params)
        if response.status_code == 200:
            data = response.json()
            rsp = data['imgurl']
            return rsp
        else:
            return None
            print('生成图片失败')

    @add_receiver_info
    def handle_识图(self, msg):
        #AI识图
        url = "https://api.pearktrue.cn/api/airecognizeimg/"
        file_path = self.file_path
        with open(file_path, "rb") as f:
            files = {"file": ("file", f, 'image/jpeg')}
            response = requests.post(url, files = files)
        if response.status_code == 200:
            print('图片上传成功')
            data = response.json()
            rsp = data["result"]
            #使用大语言模型加强识别结果
            #rsp = self.chat.get_answer(rsp, (msg.roomid if msg.roomid else msg.sender)).split('####')[0]  #用split删除广告消息
            return rsp
            print('图片识别成功')
        else:
            return None
            print('图片上传失败') 

    @add_receiver_info
    def handle_查榜(self, msg):
        # 门户热搜榜单，格式：热搜+哔哩哔哩，百度，知乎，百度贴吧，少数派，IT之家，澎湃新闻，今日头条，微博热搜，36氪，稀土掘金，腾讯新闻
        title = msg.content.replace('查榜', "").strip()
        if not title:
            return f"1.功能介绍：获取热搜榜单，支持哔哩哔哩，百度，知乎，百度贴吧，少数派，IT之家，澎湃新闻，今日头条，微博热搜，36氪，稀土掘金，腾讯新闻\n2.调用格式：\n查榜今日头条"
        params = {'title':title}
        response = requests.get('https://api.pearktrue.cn/api/dailyhot', params=params)
        data = response.json()
        if response.status_code == 200:
            print("正在生成榜单")
            print(data)
            topics = data['data']  # 来自请求的问题数据列表
            output = ''
            for i, topic in enumerate(topics):
                if i >= 20: #只获取前十五个话题
                    break
                output += f'{i+1}.{topic["title"][:27]}\n'  # 获取标题
            rsp = output
            return rsp
            print("榜单获取成功")
        else:
            return None
            print("榜单获取失败")

    @add_receiver_info
    def handle_不可说(self, msg): 
        # 不可说
        yulu = msg.content.replace('不可说', "").strip() #支持哲学、污妖王、毒鸡汤、朋友圈、渣男、舔狗、骚话、情话、笑话
        if not yulu:
            return f"1.功能介绍：\n佛曰：不可说，支持：不可说\n2.调用格式：\n不可说情话"
        yulu_dict = {'哲学':'jdyl/zhexue.php','污妖王':'wuyaowang','毒鸡汤': 'dujitang','朋友圈':'jdyl/pyq.php',"渣男": 'random/zhanan?type=text', '舔狗':'jdyl/tiangou.php', '骚话':'jdyl/saohua.php','情话':'jdyl/qinghua.php','笑话':'jdyl/xiaohua.php'}
        tail = yulu_dict[yulu]
        url = 'https://api.pearktrue.cn/api/'+tail
        response = requests.get(url)                 
        if response.status_code == 200:
           content = re.split('<br>', response.text)
           content = [line.strip().replace('-', '') for line in content if line.strip() != ""]
           rsp = "\n".join(content)
           return rsp
           print("语录生成成功")
        else:
            return None
            print("语录生成失败")

    @add_receiver_info
    def handle_头像(self, msg):
        # 根据文字设定生成头像
        text = msg.content.replace('头像', "").strip() 
        if not text:
            return f"1.功能介绍：\n根据设定生成头像\n2.调用格式：头像机器人女友"
        try:
            response = requests.get('https://api.pearktrue.cn/api/aiheadportrait/?prompt='+ text)
            response.raise_for_status()
            data = json.loads(response.text)
            imgurl = data['imgurl'] # 用方括号访问键
            response = requests.get(imgurl, stream=True) # 注意这里用的是imgurl而不是image_url
            response.raise_for_status()
            # 将图片数据写入文件
            with open(r'C:\Users\Raimbault\avatar.png', 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)            
            rsp = r"C:\Users\Raimbault\avatar.png"
            return rsp
            print("头像生成成功")
        except (requests.RequestException, KeyError, IOError) as e:
            return None
            print('头像生成失败，错误代码:', e)

    @add_receiver_info
    def handle_到账(self, msg):
        #生成支付宝到账语音
        content = msg.content.replace('支付宝到账', "").strip()
        if not content:
            return f"1.功能介绍：\n生成支付宝到账语音\n2.调用格式：\n到账100000000000000"
        types = 'json'
        number = content
        params = {'number':number, 'type':types}
        response = requests.get('https://api.pearktrue.cn/api/alipay', params = params)
        if response.status_code == 200:
            data = json.loads(response.text)
            rsp = [data.get('audiourl', 'Not found')]
            rsp = rsp[0]
            return rsp
            print("语音生成成功")
        else:
            return None
            print("语音生成失败")

    @add_receiver_info
    def handle_追番(self, msg):
        #获取最新番剧更新情况
        response = requests.get('https://api.pearktrue.cn/api/todayanime/')
        data = response.json()
        if data['code'] == 200:                        
            print("正在生成榜单") 
            animes = data['data']  # 获取_anime数组
            output = '最新的番剧更新如下：\n'
            for i, anime in enumerate(animes):
                output += f'{i+1}. '
                output += f'{anime["title"]}\n'  # 获取标题
                output += f'状态: {anime["status"]}\n'  # 获取状态
            output += '以上就是番剧的最近更新。\n'
            rsp = output
            return rsp
            print("获取成功")
        else:
            return None
            print("获取失败")

    @add_receiver_info
    def handle_抖音(self, msg):
        #获取抖音热榜并将序号传递给【搜抖音】
        response = requests.get('https://api.pearktrue.cn/api/dy/hot/')
        data = response.json()
        if data['code'] == 200:                        
            print("正在生成榜单")                        
            topics = data['data']['current']
            output = f'最新的抖音热搜榜单如下：\n'
            for i, topic in enumerate(topics):
                if i >= 20: #只获取前二十个话题
                    break
                self.douyin_hotlist[i+1] = topic["topic_name"]
                output += f'{topic["rank"]}.'
                output += f'{topic["topic_name"]}\n'
                #output += f'热度: {topic["topic_index"]}\n'
                #output += f'状态: {topic["status"]}\n'
                #output += f'类别: {topic["category"]}\n'
            output += f'请输入“搜抖音+数字”搜索视频\n'
            rsp = output
            return rsp
            print(f"榜单获取成功\n{self.douyin_hotlist}")
        else:
            return None
            print("榜单获取失败")

    @add_receiver_info
    def handle_搜抖音(self, msg):
        # 抖音检索视频 
        content = msg.content.replace('搜抖音', "").strip()
        if not content:
            return f"1.功能介绍：\n根据【抖音】序号或者名字搜索抖音\n2.调用格式：\n格式1：搜抖音1\n格式2：搜抖音张大仙\n格式3：搜抖音3张大仙\n注：3表示第3页，默认第1页"
        page = 1  # 默认页码为1
        if content.isdigit():
            rank = int(content)
            if rank in self.douyin_hotlist:
                keyword = self.douyin_hotlist[rank]
            else:
                return "请先调用【抖音】，若已抖音请检查序号"
        else:
            # 检查第一个字符是否为数字，来确定页码
            if content[0].isdigit():
                # 如果是数字，提取页码
                page_end_index = 1
                while page_end_index < len(content) and content[page_end_index].isdigit():
                    page_end_index += 1
                page = int(content[:page_end_index])
                keyword = content[page_end_index:]
            else:
                # 如果不是数字，整个内容都是关键词
                keyword = content    
        params = {'keyword':keyword, 'page':page}
        response = requests.get('https://api.pearktrue.cn/api/dy/search', params = params)
        data = response.json()
        if data['code'] == 200: 
            print("正在处理搜索结果")                       
            videos = data['data']
            output = f'我为您找到了以下结果：\n'
            for i, video in enumerate(videos):
                if i >= 10:  # 一页只有10条，i<=10
                    break
                self.douyin_downloadlink[i+1] = video["linkurl"]                           
                output += f'Top -{video["top"]}-\n'
                output += f'时间:{video["time"]}\n'
                output += f'作者:{video["nickname"]}\n'
                #output += f'作者ID: {video["uid"]}\n'
                #output += f'视频封面: {video["videocover"]}\n'
                #output += f'视频链接: {video["linkurl"]}\n'                           
                output += f'简介:{video["description"][:22]}···\n'
                output += f'--------------------------------'
                output += f'\n'
            output += f'请输入“看抖音+数字”查看视频\n'
            rsp = output
            return rsp
            print(f"链接获取成功\n{self.douyin_downloadlink}")
        else:
            return None
            print("链接获取失败") 

    @add_receiver_info
    def handle_看抖音(self, msg):
        #抖音解析链接下载视频
        rank = int(msg.content.replace('看抖音', "").strip())
        if not rank:
            return f"1.功能介绍：\n根据【搜抖音】序号或名字看抖音\n2.调用格式：\n格式1：看抖音1\n格式2：看抖音懂车帝"
        if rank in self.douyin_downloadlink:
            base_url = self.douyin_downloadlink[rank]
            params = {"url":base_url}
            try:
                response = requests.get('https://api.pearktrue.cn/api/video/douyin', params =params, timeout = 5)
                response.raise_for_status()
                data = json.loads(response.text)
                url = data['data']['url']  # Modify this line
                response = requests.get(url, stream=True, timeout = 5)
                response.raise_for_status() 
                print("视频解析成功")               
            except (requests.RequestException, KeyError, IOError) as e:
                print("视频下载失败，错误代码:", e)

            # 将数据写入文件
            with open(r'C:\Users\Raimbault\douyin.mp4', 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            print("视频下载成功")
            rsp = r"C:\Users\Raimbault\douyin.mp4"
            return rsp
        else:
            return None
            print("输入的排名不存在")

    @add_receiver_info
    def handle_刷抖音(self, msg):
        #随机获取抖音小姐姐视频
        response = requests.get('https://v.api.aa1.cn/api/api-girl-11-02/index.php?type=json')
        if response.status_code == 200:
            print('视频获取成功.')
            data = json.loads(response.text)
            relative_url = data.get('mp4', 'Not found')
            rsp = 'https:' + relative_url
            return rsp
        else:
            return None
            print('视频获取失败')

    @add_receiver_info
    def handle_小姐姐(self, msg):
        #随机生成小姐姐图片 
        types = 'img'
        mode = 1,3,8 #注意单个数字以逗号结尾，多个数字以逗号分隔，1：微博美女，2：IG图包，3：cos美女，5：Mtcos美女，7：美腿，8：Coser分类，9：兔玩映画
        params = {'type':types, 'mode':mode}
        mode_dict = {1:"微博美女", 2:"IG图包", 3:"Cos美女", 5:"Mtcos美女", 7:"美腿", 8:"Coser分类", 9:"兔玩映画"}
        names = ', '.join(mode_dict[number] for number in mode)
        response = requests.get('https://3650000.xyz/api', params = params)                        
        soup = BeautifulSoup(response.content, 'html.parser')                        
        rsp = [tag.get('src') for tag in soup.find_all(src=True)]
        rsp = rsp[0]
        return rsp
        print("小姐姐来啦")    

    @add_receiver_info
    def handle_百家姓(self, msg):
        name = msg.content.replace("百家姓", "").strip()
        if not name:
            return f"1.功能介绍：\n查看百家姓排行\n2.调用格式：\n百家姓张"
        url = "https://api.pearktrue.cn/api/bjx"
        params = {"name":name}
        try:
            response = requests.get(url, params = params, timeout= 5)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return f"视频下载失败，错误代码:{e}"
        data = response.json()
        rsp = f"{data['msg']}\n姓氏：{data['name']}\n排名：{data['top']}"
        return rsp

    @add_receiver_info
    def handle_发证书(self, msg):
        # 生成证书，title限制6字(超字数无法生成)，text在32字以内显示最佳
        s = msg.content.replace('发证书', "").strip()
        if not s:
            return f"1.功能介绍：\n生成证书，标题限6字以内\n2.调用格式：\n发证书，颁发[标题]给@[姓名]，[证书正文]"
        match = re.match(".*发(.*)给@([^，]*)\u2005，(.*)", s)
        title = match.group(1)
        name = match.group(2)
        text = match.group(3)
        params = {'name': name, 'title': title, 'text': text}
        response = requests.get('https://api.pearktrue.cn/api/certificate/', params=params)
        if response.status_code == 200:
            print("证书生成成功") 
            with open(r'C:\Users\Raimbault\output_image.jpg', 'wb') as f:
                f.write(response.content)
            print("证书下载成功") 
            rsp = r"C:\Users\Raimbault\output_image.jpg "
            return rsp                     
        else:
            return None
            print("证书生成失败")

    @add_receiver_info
    def handle_搜题(self, msg):
        # 百度搜题
        question = msg.content.replace('搜题', "").strip()
        if not question:
            return f"1.功能介绍：\n百度教育搜题\n2.调用格式：\n搜题根据契税法律的规定"
        params = {'question':question}
        self.sendTextMsg(f"正在为您查询\n您要找的题目为：\n{question}\n正在查询，请您耐心等待···", msg.roomid)
        response = requests.get('https://api.pearktrue.cn/api/baidutiku', params = params)
        if response.status_code == 200:
            data = response.json()
            question = data["data"]["question"]
            options = data["data"]["options"]
            answer = data["data"]["answer"]
            # 使用'\n'把列表中的所有选项链接起来，并且它们之间会换行
            options_str = '\n'.join(options)
            rsp = f"{question}\n\n{options_str}\n\n{answer}"
            return rsp
            print("搜题成功")            
        else:
            return None
            print("搜题失败")

    @add_receiver_info
    def handle_卡路里(self, msg):
        #查询食品所含热量
        food = msg.content.replace('卡路里', "").strip()
        if not food:
            return f"1.功能介绍：\n查食物热量\n2.调用格式：\n卡路里橘子"
        params = {'food':food}
        response = requests.get('https://api.pearktrue.cn/api/calories', params = params)
        if response.status_code == 200:
            data = response.json()
            foods = data['data']  # 来自请求的食物数据列表
            output = f'查找的食物: {data["food"]}\n共找到 {data["count"]} 类食物\n'
            output += f'食物{food}热量如下：\n'
            for i, food in enumerate(foods):
                output += f'{i+1}. '
                output += f'{food["food"]}：{food["calories"]}\n'  # 获取食物以及其热量
            rsp = output
            return rsp
            print("食物热量查询成功")
        else:
            return None
            print("食物热量查询失败")

    @add_receiver_info
    def handle_查星座(self, msg):
        # 查询星座运势，支持今日、明日、本周、本月、今年、爱情运势
        message = msg.content.replace('查星座', "").strip()
        if not message:
            return f"1.功能介绍：\n查星座运势，支持今日、明日、本周、本月、今年、爱情运势\n2.调用格式：\n查星座白羊座今日运势"
        time_dict = {"今日": "today", "明日": "nextday", "本周": "week",
                     "本月": "month", "今年": "year", "爱情": "love"}
        xingzuo_dict = {"白羊座": "aries", "金牛座": "taurus", "双子座": "gemini",
                        "巨蟹座": "cancer", "狮子座": "leo", "处女座": "virgo",
                        "天秤座": "libra", "天蝎座": "scorpio", "射手座": "sagittarius",
                        "摩羯座": "capricorn", "水瓶座": "aquarius", "双鱼座": "pisces"}
        time = time_dict[message[3:5]]
        xingzuo = xingzuo_dict[message[:3]]
        params = {'time': time, 'type': xingzuo}
        response = requests.get('https://api.vvhan.com/api/horoscope', params=params)
        if response.status_code == 200:
            data = json.loads(response.text)
            if data["success"]:
                data = data["data"]
                output = f'以下是查询到的内容：\n\n'
                output += f'星座: {data["title"]}\n'
                output += f'类型: {data["type"]}\n'
                output += f'日期: {data["time"]}\n'
                if 'luckynumber' in data:
                    output += f'幸运数字: {data["luckynumber"]}\n'
                if 'luckycolor' in data:
                    output += f'幸运色: {data["luckycolor"]}\n'
                if 'luckyconstellation' in data:
                    output += f'速配星座: {data["luckyconstellation"]}\n'
                output += f'建议:\n宜: {data["todo"]["yi"]}\n忌: {data["todo"]["ji"]}\n'
                output += f'简评: {data["shortcomment"]}\n\n'
                output += '运势指数:\n'
                # 添加簿记来将英文键转换为中文
                key_map = {'all': '总运', 'love': '爱情', 'work': '工作',
                           'money': '财运', 'health': '健康',
                           'girl': '女生', 'boy': '男生',
                           'decompression': '减压', 'openluck': '缘分'}
                # 循环遍历并替换键
                for k, value in data["index"].items():
                    output += f'{key_map.get(k, k)}: {value}\n'
                output += f'\n'
                output += '运势详解:\n'
                for k, value in data["fortunetext"].items():
                    output += f'{key_map.get(k, k)}: {value}\n\n'
                rsp = output
                return rsp
            else:
                return None
                print("星座查询失败")

    @add_receiver_info
    def handle_查油价(self, msg):
        # 查全国油价，格式为：查油价+省份
        province = msg.content.replace('查油价', "").strip()
        if not province:
            return f"1.功能介绍：\n查各省油价\n2.调用格式：\n查油价江苏"
        response = requests.get('https://api.pearktrue.cn/api/oil')        
        if response.status_code == 200:
            data = response.json()
            prices_info = None            
            for entry in data["data"]:
                province_entry = entry["province"]                
                if province_entry == province:
                    prices_info = "".join([f"{fuel}号:{price}元\n" for fuel, price in entry["prices"].items()])
                    break            
            if prices_info is not None:
                print("油价查询成功")
                rsp = f"{province}油价如下:\n{prices_info}"
                return rsp
            else:
                print("找不到相关省份的油价信息")
                return None
        else:
            print("油价查询失败")
            return None


    @add_receiver_info
    def handle_查号码(self, msg):
        # 查骚扰电话
        mobile = msg.content.replace('查号码', "").strip()
        if not mobile:
            return f"1.功能介绍：\n查手机号码\n2.调用格式：查号码13500000000"
        params = {'mobile':mobile}
        response = requests.get('https://api.pearktrue.cn/api/phone', params = params)
        if response.status_code == 200:
            data = response.json()  # 使用 json() 方法解析返回的 JSON 数据
            output = f'查询号码: {data["mobile"]}\n'  # 添加手机号码
            output += f'所在省份: {data["info"]["province"]}\n'  # 添加省份
            output += f'所在城市: {data["info"]["city"]}\n'  # 添加城市
            output += f'运营商: {data["info"]["operator"]}\n\n'  # 添加运营商
            for d in data["data"]:
                output += f'服务名称: {d["name"]}\n查询结果: {d["msg"]}\n\n'
            rsp = output.strip()
            print("号码查询成功")
            return rsp
        else:
            return None
            print("号码查询失败")

    @add_receiver_info
    def handle_查天气(self, msg):
        # 询问天气，询问格式为：搜天气 河北-唐山
        city_name = msg.content.replace("查天气", "").strip()
        if not city_name:
            return f"1.功能介绍：查询明日天气\n2.调用格式：\n查天气河北-唐山"
        # 获取天气信息
        rsp = get_weather(city_name)
        return rsp

    @add_receiver_info
    def handle_查功能(self, msg):
        commands_list = [f"{i}. {key}" for i, key in enumerate(self.commands.keys(), 1)]
        line_length = 25
        output = ""
        line = ""
        for command in commands_list:
            # 预估加入新命令后的长度
            new_line_length = len(line + command)
            if new_line_length < line_length:
                # 如果不超过限制，加入当前命令
                line += command + "  "  # 两个空格作为分隔
            else:
                # 如果超过限制，则先换行
                output += line.strip() + "\n"
                line = command + "  "  # 从新的一行开始
        # 加入最后一行
        output += line.strip()
        return output

    @add_receiver_info
    def handle_讲述人(self, msg):
        #根据文字生成语音
        content =  msg.content.replace("讲述人", "").strip()
        if not content:
            return f"1.功能介绍：\n讲述文本，支持1-163号讲述人\n2.调用格式：\n讲述人8，你是一朵盛开的花，在生命中散发着美丽的光芒"
        index, text = content.split("，")
        index = int(index)
        name_dict = {1: '宇祥', 2: '宇蓝', 3: '蕊柔', 4: '宇智', 5: '宇希', 6: '希儿', 7: '蕊诗', 8: '蕊雪', 9: '蕊姗', 10: '珊儿', 11: '婉儿', 12: '智宸', 13: '宇昊', 14: '宇铭', 15: '宇伟', 16: '紫瑶', 17: '紫阿', 18: '紫雪', 19: '紫娜', 20: '紫芸', 21: '宇全', 22: '玲儿', 23: '艾婷', 24: '宇诚', 25: '宇盛', 26: '宇栋', 27: '宇光', 28: '艾琳', 29: '艾莉', 30: '艾雯', 31: '艾诗', 32: '宇驰', 33: '艾薇', 34: '艾洁', 35: '艾蕊', 36: '宇骏', 37: '宇康', 38: '艾悦', 39: '艾冉', 40: '艾楠', 41: '宇铭', 42: '艾婧', 43: '艾露', 44: '艾思', 45: '艾媛', 46: '艾茜', 47: '艾菲', 48: '艾雅', 49: '宇泽', 50: '艾冉', 51: '晓萱', 52: '晓辰', 53: '晓晓', 54: '晓伊', 55: '云健', 56: '云夏', 57: '云扬', 58: '云希', 59: '晓贝', 60: '晓妮', 61: '晓枫', 62: '晓新', 63: '云辰', 64: '沁荷', 65: '芸语', 66: '语嫣', 67: '蕊珠', 68: '沁娜', 69: '沁蕾', 70: '宇璋', 71: '馨月', 72: '馨兰', 73: '宇尚', 74: '宇同', 75: '馨欣', 76: '馨瑶', 77: '宇韦', 78: '宇', 79: '晋', 80: '蕊芬', 81: '宇晋', 82: '蕊莉', 83: '沁雨', 84: '沁香', 85: '宇康', 86: '馨逸', 87: '沁莲', 88: '宇栋', 89: '馨荣', 90: '芸渲', 91: '芸露', 92: '芸梅', 93: '蕊若', 94: '蕊晗', 95: '沁美', 96: '芸柔', 97: '蕊韵', 98: '宇彦', 99: '芸茜', 100: '蕊诗', 101: '晓墨', 102: '云枫', 103: '晓悠', 104: '晓睿', 105: '晓梦', 106: '云野', 107: '晓双', 108: '晓秋', 109: '云皓', 110: '晓颜', 111: '云泽', 112: '晓甄', 113: '云非', 114: '云溢', 115: '云信', 116: '源司', 117: '银时', 118: '绫音', 119: '绚濑', 120: '星奈', 121: '莉亚', 122: '莉娜', 123: '琉璃', 124: '力丸', 125: '小雪', 126: '翔太', 127: '小春', 128: '小梓', 129: '春香', 130: '佑果', 131: '小彩', 132: '美月', 133: '影山', 134: '紫苑', 135: '时雨', 136: '龙之介', 137: '梨斗', 138: '悠里', 139: '穗乃香', 140: 'Liam', 141: 'Mason', 142: 'Skylar', 143: 'Vanessa', 144: 'Kayla', 145: 'Sadie', 146: 'Daniel', 147: 'Jacob', 148: 'Natalie', 149: 'Tyler', 150: 'Lily', 151: 'Thomas', 152: 'Harper', 153: 'Henry', 154: 'Naomi', 155: 'Ethan', 156: 'Emma', 157: 'Ava', 158: 'Lucas', 159: 'Chloe', 160: 'Caleb', 161: 'Sofia', 162: 'Gabriel', 163: 'Ivy'}
        info_dict = {1: '男-磁性 阅读 纪录片', 2: '男 广告宣传 新闻解说', 3: '女 解说 纪录片 阅读', 4: '男 -低沉磁性 解说 纪录片', 5: '女-轻柔 语录 影视解说', 6: '女-温柔 阅读', 7: '女 广告宣传 新闻解说', 8: '女-空灵纯净 广告解说', 9: '女-抒情', 10: '女 解说广告 纪录片', 11: '女-饱满 广告 解说', 12: '男-沉稳 播报解说', 13: '男 新闻播报', 14: '男-磁性 纪录片 广告宣传 新闻解说', 15: '男-低沉 解说 纪录片', 16: '女-温柔 阅读 解说', 17: '女 阅读 解说', 18: '女 语录 广告 纯净', 19: '女 阅读 解说', 20: '女 阅读 解说 新闻解说', 21: '男 解说 广告', 22: '女 阅读 解说 广告宣传', 23: '女 旁白 解说 广告宣传', 24: '男 旁白 广告宣传', 25: '男 客服', 26: '男 客服 广告宣传', 27: '男 旁白', 28: '女 旁白 解 说 广告宣传', 29: '女 旁白 解说 广告宣传', 30: '女 旁白 解说 广告宣传', 31: '女 旁白 解说 广告宣传', 32: '男 旁白', 33: '女 旁白 解说 广告宣传', 34: '女 旁白 解说 广告宣传', 35: '女 旁白 解说 广告宣传', 36: '男 旁白', 37: '男 旁白', 38: '女 旁白 解说 广告宣传', 39: '女 旁白 解说 广告宣传', 40: '女 旁白 广东 解说 广告宣传', 41: '男 旁白', 42: '女 旁白 解说 广告宣传', 43: '女 旁白 解说 广告宣传', 44: '女 旁白 解说 广告宣传', 45: '女 旁白 解说 广告宣传', 46: '女 旁白 解说 广告宣传', 47: '女 旁白 解说 广告宣传', 48: '女 旁白 解说 广告宣传', 49: '男 旁白 客服', 50: '情感女声 广告 阅读 解说', 51: '情感女声 广告宣传 旁白', 52: '知性女生 抖音热门 解说 广告宣传 旁白', 53: '情感 女 解 说 新闻 广告宣传 情感故事', 54: '儿童音 女 阅读 游戏 动漫', 55: '情感男声 男-中年 解说 旁白', 56: '儿童音 男 解说 游戏 动漫', 57: '青年男声 男-年轻人 新闻广告 客服 解说', 58: '解说小帅 解说小帅 抖音热门 影视 纪录片', 59: '东北 辽宁', 60: '陕西 陕西 方言', 61: '情感女声 台湾', 62: '情感女声 台湾', 63: '台湾 台湾 广告宣传 客服', 64: '女-低沉沉稳 阅读', 65: '女-清晰 广告解说 教育', 66: '女 广告宣传 新闻播报', 67: '女-宏亮 新闻播报', 68: '女-平淡 播报', 69: '女-饱满平淡 广告新闻', 70: '男 解说纪录片', 71: '女-温暖富有情感 阅读', 72: '女-沉稳清脆 广告宣传 解说新闻', 73: '男-磁性沉稳', 74: '男 阅读 纪录片', 75: '女-平淡 广东 播报 广告', 76: '女 广告宣传 新闻解说', 77: '男-沉稳', 78: '', 79: '男 阅读 广告宣传', 80: '女-抒情 广告宣传 解说', 81: '男 旁白 客服', 82: '女-富有情感 广告 新闻', 83: '女 新闻广告', 84: '女-灵动 阅读', 85: '男 纪录片', 86: '女 纯净 阅 读 广告宣传', 87: '女 新闻解说', 88: '男 旁白 客服', 89: '女-轻柔', 90: '女-沉稳 新闻资讯 影视解说', 91: '女 新闻资讯 语录', 92: '女-低沉', 93: '女-空灵轻柔 语录百科 广告宣传', 94: '女-磁性知性 阅读 广告', 95: '女 阅读', 96: '女 阅读 广告', 97: '女 语录', 98: '男 阅读', 99: '女-沙哑', 100: '女-富有情感', 101: '青年女声 广告 解说', 102: '磁性男声  广告宣传 解说播报 百科', 103: '儿童音 女-儿童 解说 游戏 动漫', 104: '老年女声 沉稳 解说 百科 情感', 105: '年轻女声 女-年轻人广告 旁白', 106: '成熟男声 解说 广告宣传 播报', 107: '儿童音 女-儿童 动漫 游戏 解说', 108: '中年女声 沉稳 宣传 纪录片', 109: '中年男声 男 广告宣传 百科 解说', 110: '青年女声 女 解说广告 旁白 客服', 111: '成熟浑厚 男 纪录片 广告 旁白', 112: '温柔女声 阅读 广告 解说', 113: '香港 香港 方言', 114: '香港 香港 方言', 115: '香港 香港 方言', 116: '男', 117: '男', 118: '女', 119: '女', 120: '女', 121: '女', 122: '女', 123: '女', 124: '男', 125: '女', 126: '男', 127: '女', 128: '女', 129: '女', 130: '女', 131: '女', 132: '女', 133: '男', 134: '女', 135: '女', 136: '男', 137: '女', 138: '女', 139: '女', 140: ' 男-英文', 141: '男-英文', 142: '女-英文', 143: '女-英文', 144: '女-英文', 145: '女-英文', 146: '男-西班牙语', 147: '男-西班牙语', 148: '女-西班牙语', 149: '男-葡萄牙语', 150: '女-葡萄牙语', 151: '男-日语', 152: '女-日语', 153: '男-俄语', 154: '女-俄语', 155: '男-德语', 156: '女-德语', 157: '女-德语', 158: '男-法语', 159: '女-法语', 160: '男-韩 语', 161: '女-韩语', 162: '男-意大利语', 163: '女-意大利语'}
        speaker = name_dict[index]
        info = info_dict[index]
        params = {'speak':speaker, 'text':text}
        response = requests.get('https://api.pearktrue.cn/api/aivoicenet', params = params)
        if response.status_code == 200:
            print('生成讲述语音成功')
            data = json.loads(response.text)
            rsp = [data.get('voiceurl', 'Not found')]
            rsp = rsp [0]
            return rsp
            print('下载讲述语音成功')
        else:
            return None
            print("生成讲述语音失败")    
