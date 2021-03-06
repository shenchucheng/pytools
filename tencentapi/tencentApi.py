#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import operator
import os
import random
import time
import urllib.parse

import urllib3
import yaml


class Api:
    def __init__(self, conf_path="", conf_dir=""):
        """
        :param conf_path: config file path
               default: .pyproject/tencentapi/api.conf at config_dir
        :param conf_dir: files produced saved at this dir
               default: ~/.pyproject/tencentapi/
        """
        if not conf_dir:
            conf_dir = os.path.join(os.path.expanduser("~"), ".pyconfig", "tencentapi")
            if not os.path.exists(conf_dir):
                os.makedirs(conf_dir)
        if not conf_path:
            conf_path = os.path.join(conf_dir, "tencentapi.conf")
        self.conf_dir = conf_dir
        self.conf_path = conf_path
        self.__conf_doc = ''
        self.config = self.parser()
        self.secretId = self.config["secretId"]
        self.secretKey = self.config["secretKey"]
        try:
            from local.loghelper import basicConfig
            basicConfig()
        except ImportError:
            from logging import basicConfig
        basicConfig(filename=os.path.join(self.conf_dir, "log.txt"))

    @property
    def conf_doc(self):
        if not self.__conf_doc:
            with open(self.conf_path, "a+") as f:
                if f.tell() > 0:
                    f.seek(0)
                    self.__conf_doc = f.read()
                else:
                    self.__conf_doc = _conf_doc_pre
        return self.__conf_doc

    @conf_doc.setter
    def conf_doc(self, doc: str):
        # lines = self.conf_doc.splitlines(True)
        # doc_pre = "".join(lines[:5])
        lines = doc.splitlines(True)
        _ = ""
        for line in lines:
            if not line.startswith("#"):
                line = "# " + line
            _ += line
        # doc = _ if doc.startswith(doc_pre) else doc_pre+_
        if doc not in self.conf_doc:
            doc = "\n\n" + doc
            self.__conf_doc += doc

    def create_conf(self, conf=""):
        with open(conf or self.conf_path, "w") as f:
            f.write(self.conf_doc)

    # def create_conf(self):
    #     conf_path = self.conf_path
    #     self.__create_conf(conf_path)
        # if os.path.exists(conf_path):
        #     with open(conf_path) as f:
        #         _ = ""
        #         for line in f:
        #             if line.startswith("#"):
        #                 continue
        #             if line == "\n":
        #                 continue
        #             _ += line
        #     with open(conf_path, "w") as f:
        #         f.write(self.conf_doc+"\n"+_)
        # else:
        #     self.__create_conf(conf_path)

    def parser(self):
        """
        parser the args for configure file
        :return: config dict
        """
        if not os.path.exists(self.conf_path):
            self.create_conf(self.conf_path)
        with open(self.conf_path) as f:
            conf = yaml.load(f, Loader=yaml.SafeLoader)
        if conf is None:
            raise NotImplementedError(
                "Fatal Error: TencentApi conf file without setting. " +
                "File has initialised in {}".format(self.conf_path)
            )
        return conf

    def get(self, action, module='cns', **params):
        config = {
            'Action': action,
            'Nonce': random.randint(10000, 99999),
            'SecretId': self.secretId,
            'SignatureMethod': 'HmacSHA256',
            'Timestamp': int(time.time()),
        }
        url_base = '{0}.api.qcloud.com/v2/index.php?'.format(module)
        params_all = dict(config, **params)
        params_sorted = sorted(params_all.items(), key=operator.itemgetter(0))
        srcStr = 'GET{0}'.format(url_base) + ''.join("%s=%s&" % (k, v) for k, v in dict(params_sorted).items())[:-1]
        signStr = base64.b64encode(
            hmac.new(bytes(self.secretKey, encoding='utf-8'),
            bytes(srcStr, encoding='utf-8'),
            digestmod=hashlib.sha256).digest()
        ).decode('utf-8')
        config['Signature'] = signStr
        params_last = dict(config, **params)
        params_url = urllib.parse.urlencode(params_last)
        url = 'https://{0}&'.format(url_base) + params_url
        http = urllib3.PoolManager()
        r = http.request('GET', url=url, retries=False)
        ret = json.loads(r.data.decode('utf-8'))
        if ret.get('code', {}) == 0:
            return ret
        else:
            raise Exception(ret)


class CnsApi(Api):
    """
    腾讯云解析记录相关接口:
    https://cloud.tencent.com/document/product/302/3875
    接口请求域名：cns.api.qcloud.com
    """
    def __init__(self, *domains, **kwargs):
        """
        :param domain: such as "baidu.com", "bing.cn"
        :param kwargs:
        """
        super().__init__(**kwargs)
        try:
            self.domains = domains or self.config["domains"]
        except KeyError:
            self.conf_doc = "# domain\n# Example\n# domains: !!set\n#   ab.com: \n#   cd.cn: \n"
            self.create_conf()
            raise Exception("domain not set,please check the config file at {}".format(self.conf_path))
        with open(os.path.join(self.conf_dir, "record.list"), "a+") as f:
            f.seek(0)
            self.records = yaml.load(f, yaml.SafeLoader) or {}

    def __record_list(self, domain, **kwargs):
        ret = self.get(action='RecordList', domain=domain, **kwargs)["data"]
        # __records = {}
        # for i in ret["records"]:
        #     __records[i.pop("name")] = i
        # ret["records"] = __records
        with open(os.path.join(self.conf_dir, "record.list"), "a+") as f:
            yaml.dump({domain: ret}, f)
        self.records[domain] = ret

    def record_list(self, *domains, update=False, **kwargs):
        """
        :param update: bool if update will update self.records
        :param domains: str 要操作的域名（主域名，不包括 www，例如：qcloud.com）
        :param kwargs:
            offset int 偏移量，默认为0。关于offset的更进一步介绍参考 接口请求参数
            length int 返回数量，默认20，最大值100
            subDomain str （过滤条件）根据子域名进行过滤
            recordType str （过滤条件）根据记录类型进行过滤
            qProjectId int （过滤条件）项目 ID
        :return:
        """
        ret = {}
        domains = domains or self.domains
        if update:
            for i in domains:
                self.__record_list(i, **kwargs)
        for i in domains:
            if i not in self.records.keys():
                self.__record_list(i, **kwargs)
            ret[i] = self.records[i]
        return ret

    def record_modify(self, domain, recordId='', subDomain='', value='',
                      recordType='', recordLine='', update=False, **kwargs):
        """
        :param domain: str 要操作的域名（主域名，不包括 www，例如：qcloud.com）
        :param subDomain: str 子域名，例如：www
        :param value: str 记录值，例如 IP：192.168.10.2，CNAME：cname.dnspod.com.，MX：mail.dnspod.com.
        :param recordId: int 解析记录的 ID，可通过 RecordList 接口返回值中的 ID 获取
        :param recordType: str 记录类型，可选的记录类型为："A"，"CNAME"，"MX"，"TXT"，"NS"，"AAAA"，"SRV"
        :param recordLine: str 记录的线路名称，例如："默认"
        :param update: if not update, will compare with cache
        :param kwargs:
        ttl int TTL 值，范围1 - 604800，不同等级域名最小值不同，默认为 600
        mx	int	MX 优先级，范围为0 ~ 50，当 recordType 选择 MX 时，mx 参数必选
        :return:
        """
        kwargs1 = {}
        if recordId:
            kwargs1["id"] = recordId
        elif subDomain:
            kwargs1["name"] = subDomain
        info = self.get_record_info(domain, update=update, fetchone=False, **kwargs1)
        if len(info) == 0:
            return {"info": "no such record"}
        elif len(info) > 1:
            return {"info": "too many records match", "value": info}
        info = info[0]
        __value, __recordId, __recordType, __recordLine = list(
            info[i] for i in ("value", "id", "type", "line")
        )
        value, recordId, recordType, recordLine = (
            value or __value,
            recordId or __recordId,
            recordType or __recordType,
            recordLine or __recordLine
        )
        # if not any((value, recordId, recordType, recordLine)):
        #     raise ValueError("Please do not let all params blank")
        if (value, recordId, recordType, recordLine) != (
                __value, __recordId, __recordType, __recordLine):
            ret = self.get(action='RecordModify', domain=domain, subDomain=subDomain,
                           value=value, recordId=recordId, recordType=recordType,
                           recordLine=recordLine, **kwargs)["data"]
            if type(ret) == dict:
                for rd in self.records[domain]["records"]:
                    if rd["id"] == recordId:
                        rd.update(ret["record"])
                        info = rd
                        break
                with open(os.path.join(self.conf_dir, "record.list"), "a+") as f:
                    yaml.dump(self.records, f)
        return info

    def record_create(self, domain, subDomain, value,
                      recordType, recordLine, **kwargs):
        """
        :param domain: str 要操作的域名（主域名，不包括 www，例如：qcloud.com）
        :param subDomain: str 子域名，例如：www
        :param value: str 记录值，例如 IP：192.168.10.2，CNAME：cname.dnspod.com.，MX：mail.dnspod.com.
        :param recordType: str 记录类型，可选的记录类型为："A"，"CNAME"，"MX"，"TXT"，"NS"，"AAAA"，"SRV"
        :param recordLine: str 记录的线路名称，例如："默认"
        :param kwargs:
        ttl int TTL 值，范围1 - 604800，不同等级域名最小值不同，默认为 600
        mx	int	MX 优先级，范围为0 ~ 50，当 recordType 选择 MX 时，mx 参数必选
        :return:
        """
        rd = self.get_record_info(domain=domain, name=subDomain,
                                  value=value, type=recordType, line=recordLine)
        if rd:
            return rd
        __ret = self.get(action='RecordCreate', domain=domain, subDomain=subDomain,
                         value=value, recordLine=recordLine, recordType=recordType, **kwargs)
        ret = __ret["data"]
        kwargs.update({"line": recordLine, "value": value, "type": recordType})
        # if type(ret) == dict:
        kwargs.update(ret["record"])
        for rd in self.records[domain]["records"].copy():
            if rd["id"] == kwargs["id"]:
                self.records[domain]["records"].remove(rd)
        self.records[domain]["records"].append(kwargs)
        return kwargs
        # else:
        #     raise Exception(ret)

    def __record_delete(self, domain, recordId):
        return self.get(action='RecordDelete', domain=domain, recordId=recordId)

    def record_delete(self, domain, safe=True, **kwargs):
        rds = self.__get_record_info(domain=domain, fetchone=False, **kwargs)
        n = len(rds)
        if n == 0:
            msg = "no such record"
        elif n > 1 and safe:
            msg = "on the safe mode, could not delete multi-record: {}\n".format(
                "; ".join(str(i["id"]) for i in rds) + "\n" + ";\n".join(str(i) for i in rds)
            )
        else:
            msg = []
            for rd in rds:
                rid = rd["id"]
                self.get(action='RecordDelete', domain=domain, recordId=rid)
                msg.append(rid)
                self.records[domain]["records"].remove(rd)
            with open(os.path.join(self.conf_dir, "record.list"), "a+") as f:
                yaml.dump(self.records, f)
        return msg

    def __get_record_info(self, domain, update=False, fetchone=True, **kwargs):
        ret = self.record_list(domain, update=update)[domain]["records"].copy()
        for i in ret.copy():
            for k, v in kwargs.items():
                if i[k] != v:
                    ret.remove(i)
                    break
                if fetchone:
                    return i
        return ret

    def get_record_info(self, domain, info="*", update=False, **kwargs):
        """
        :param domain:
        :param info: get record info based on param info,
            such as, id, type, value, updated_on
            if not set ,info=*, will match all information
        :param update: if update, update the domains
        :param kwargs: filter
            name; type; status ... ...
        :return:
        """
        ret = self.__get_record_info(domain, update=update, **kwargs)
        if info == "*":
            return ret
        if type(ret) == list:
            return list(i.get(info) for i in ret)
        return ret.get(info)

    def get_record_id(self, domain, name, **kwargs):
        return self.get_record_info(domain, name=name, info="id", **kwargs)

    def get_record_value(self, domain, name, **kwargs):
        return self.get_record_info(domain, name=name, info="value", **kwargs)

    def get_record_updated_on(self, domain, name, **kwargs):
        return self.get_record_info(domain, name=name, info="updated_on", **kwargs)


def get_conf_doc_pre():
    doc = ''
    doc += "# App: TencentAPI\n"
    doc += "# Description: Tencent api need SecretId and secretKey\n"
    doc += "# Id-Key\n"
    doc += "# How to get Id&Key see https://cloud.tencent.com/developer/article/1385239\n"
    doc += "# Example: \n"
    doc += "# secretId: idAafkSyAJohQSnRidZShsDLsDuMqYUgWecQ\n"
    doc += "# secretKey: zAuhBlapaarSHJMrKfYtheLyMgLUvqrL\n"
    return doc


_conf_doc_pre = get_conf_doc_pre()


if __name__ == "__main__":
    api = CnsApi()
    __domain = list(api.domains)[0]
    domain_info = api.record_list(__domain)
    print(domain_info)
    if not api.get_record_info(__domain, name="test"):
        __id = api.record_create(
            domain=__domain, subDomain="test",
            recordType="A", value="192.168.1.1",
            recordLine="默认"
        )
    else:
        __id = api.get_record_id(__domain, name="test")
    print(api.get_record_info(__domain, name="test", id=__id))
    api.record_modify(__domain, subDomain="test", value="127.0.0.1", )
    print(api.get_record_info(__domain, id=__id))
    api.record_delete(__domain, id=__id)
    # print(_ret)
    # c_ret = api.record_create(list(api.domains)[0], "test", "192.168.1.1", "A", "默认")
