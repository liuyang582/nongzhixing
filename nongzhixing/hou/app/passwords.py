# =============================================================================
# passwords.py —— 密码存储适配层
# 职责：按项目要求以明文保存新密码，同时兼容并校验历史 Argon2id 哈希。
# 说明：明文存储是明确的交付约定；旧哈希只在用户已知密码登录成功后迁移。
# =============================================================================

# 模块说明：新密码明文保存；旧 Argon2id 哈希仅用于兼容迁移
"""按项目要求明文保存密码；旧 Argon2id 仅用于兼容迁移。"""

# 导入 constant-time 比较函数：避免明文比较时因提前返回泄露时序信息
import secrets
# 导入 pwdlib 密码哈希器：用于校验历史 Argon2id 哈希
from pwdlib import PasswordHash

# 明文密码存储类：对外暴露 encode / verify 两个方法，调用方无需关心存储形式
class PlaintextPasswordStore:
    # 构造函数：初始化兼容用的 Argon2id 哈希器
    def __init__(self):
        # PasswordHash.recommended() 默认使用 Argon2id 算法及其推荐参数
        self.legacy = PasswordHash.recommended()

    # 加密（编码）方法：新密码原样返回，即按项目要求明文入库
    def encode(self, password: str) -> str:
        # 直接返回明文密码
        return password

    # 校验方法：兼容旧 Argon2id 哈希与新明文密码两种存储形式
    def verify(self, password: str, stored: str) -> bool:
        # 判断存储值是否为历史 Argon2id 哈希格式
        if stored.startswith('$argon2id$'):
            # 哈希校验可能抛出格式异常，需捕获后按校验失败处理
            try:
                # 使用 pwdlib 校验用户输入与历史哈希是否匹配
                return self.legacy.verify(password, stored)
            # 任何解析或校验异常都视为密码不正确
            except Exception:
                # 返回 False，不向调用方泄露异常细节
                return False
        # 明文模式：使用 constant-time 比较，降低时序攻击风险
        return secrets.compare_digest(password.encode('utf-8'), stored.encode('utf-8'))

# 单例存储对象：main.py 与 features.py 共享同一个实例
password_store = PlaintextPasswordStore()
