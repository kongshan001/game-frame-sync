"""
确定性随机数生成器

本模块提供帧同步所需的确定性随机数生成：
- DeterministicRNG: 基于 Xorshift32 算法的确定性 RNG
- SeededRNG: 基于线性同余生成器（LCG）的确定性 RNG
"""

from typing import List


class DeterministicRNG:
    """
    确定性随机数生成器
    
    使用 Xorshift32 算法，保证：
    1. 相同种子产生相同的随机序列
    2. 跨平台一致性（纯整数运算）
    3. 高性能（位运算）
    
    帧同步中的使用场景：
    - 暴击判定：if rng.chance(0.3): damage *= 2
    - 随机技能效果：effect = rng.pick(effects)
    - 随机生成：x = rng.range(100, 500)
    - 洗牌：shuffled_deck = rng.shuffle(deck)
    
    重要：所有客户端必须使用相同的种子初始化！
    
    属性:
        state (int): 
            RNG 的内部状态（32位整数）。
            每次调用随机函数后都会改变。
            可以通过 get_state() / set_state() 保存和恢复。
    
    示例:
        rng = DeterministicRNG(seed=12345)
        
        # 所有客户端得到相同的结果
        damage = rng.range(10, 20)      # 例如：15
        is_crit = rng.chance(0.3)       # 例如：True
        target = rng.pick(enemies)      # 例如：enemies[2]
    """
    
    def __init__(self, seed: int):
        """
        初始化 RNG
        
        Args:
            seed: 随机种子（所有客户端必须使用相同值）
        
        Note:
            种子 0 会被自动改为 1（算法要求状态非零）
        """
        self.state = seed & 0xFFFFFFFF
        if self.state == 0:
            self.state = 1
    
    def next_uint32(self) -> int:
        """
        生成下一个 32 位无符号整数
        
        使用 Xorshift32 算法，纯位运算，保证确定性。
        
        Returns:
            随机整数 [0, 4294967295]
        """
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17)
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x
    
    def next_int(self) -> int:
        """
        生成有符号整数
        
        Returns:
            随机整数 [-2147483648, 2147483647]
        """
        return self.next_uint32() - 0x80000000
    
    def range(self, min_val: int, max_val: int) -> int:
        """
        生成指定范围的随机整数
        
        Args:
            min_val: 最小值（包含）
            max_val: 最大值（包含）
        
        Returns:
            [min_val, max_val] 范围内的整数
        
        示例:
            damage = rng.range(10, 20)  # 10-20 之间的随机伤害
        """
        if min_val == max_val:
            return min_val
        
        span = max_val - min_val + 1
        return min_val + (self.next_uint32() % span)
    
    def uniform(self) -> float:
        """
        生成 [0, 1) 范围的浮点数
        
        注意：虽然返回浮点数，但由于输入是确定性的，
        输出也是确定性的。
        
        Returns:
            随机浮点数 [0.0, 1.0)
        """
        return self.next_uint32() / 0x100000000
    
    def uniform_range(self, min_val: float, max_val: float) -> float:
        """
        生成指定范围的随机浮点数
        
        Args:
            min_val: 最小值
            max_val: 最大值
        
        Returns:
            [min_val, max_val) 范围内的浮点数
        """
        return min_val + self.uniform() * (max_val - min_val)
    
    def chance(self, probability: float) -> bool:
        """
        以给定概率返回 True
        
        用于概率性事件判定（暴击、闪避等）。
        
        Args:
            probability: 概率 [0.0, 1.0]
        
        Returns:
            True 以给定概率，否则 False
        
        示例:
            if rng.chance(0.3):  # 30% 概率暴击
                damage *= 2
        """
        return self.uniform() < probability
    
    def pick(self, items: List) -> any:
        """
        从列表中随机选择一个元素
        
        Args:
            items: 列表（非空）
        
        Returns:
            随机选择的元素，空列表返回 None
        
        示例:
            effect = rng.pick(['burn', 'freeze', 'poison'])
        """
        if not items:
            return None
        index = self.range(0, len(items) - 1)
        return items[index]
    
    def shuffle(self, items: List) -> List:
        """
        Fisher-Yates 洗牌算法（确定性）
        
        对列表进行随机打乱，返回新列表。
        相同种子总是产生相同的打乱结果。
        
        Args:
            items: 要洗牌的列表
        
        Returns:
            洗牌后的新列表（原列表不变）
        
        示例:
            deck = rng.shuffle(list(range(52)))  # 洗一副牌
        """
        result = items.copy()
        n = len(result)
        for i in range(n - 1, 0, -1):
            j = self.range(0, i)
            result[i], result[j] = result[j], result[i]
        return result
    
    def get_state(self) -> int:
        """
        获取当前状态
        
        用于保存 RNG 状态，之后可以恢复。
        常用于回滚重放。
        
        Returns:
            当前状态值（32位整数）
        """
        return self.state
    
    def set_state(self, state: int):
        """
        设置状态
        
        用于恢复之前保存的 RNG 状态。
        
        Args:
            state: 之前保存的状态值
        """
        self.state = state & 0xFFFFFFFF
        if self.state == 0:
            self.state = 1


class SeededRNG:
    """
    基于线性同余生成器（LCG）的确定性 RNG
    
    使用经典的 LCG 算法，参数来自 Numerical Recipes。
    比 Xorshift32 稍慢，但更容易理解。
    
    类常量:
        MULTIPLIER (1664525): LCG 乘数
        INCREMENT (1013904223): LCG 增量
        MODULUS (2^32): 模数
    
    属性:
        state (int): RNG 内部状态
    """
    
    MULTIPLIER = 1664525
    INCREMENT = 1013904223
    MODULUS = 2 ** 32
    
    def __init__(self, seed: int):
        """
        初始化 RNG
        
        Args:
            seed: 随机种子
        """
        self.state = seed % self.MODULUS
        if self.state == 0:
            self.state = 1
    
    def next(self) -> int:
        """
        生成下一个随机数
        
        Returns:
            随机整数 [0, 2^32-1]
        """
        self.state = (self.MULTIPLIER * self.state + self.INCREMENT) % self.MODULUS
        return self.state
    
    def range(self, min_val: int, max_val: int) -> int:
        """
        生成范围整数
        
        Args:
            min_val: 最小值
            max_val: 最大值
        
        Returns:
            [min_val, max_val] 范围的整数
        """
        return min_val + (self.next() % (max_val - min_val + 1))
    
    def uniform(self) -> float:
        """
        生成 [0, 1) 浮点数
        
        Returns:
            随机浮点数
        """
        return self.next() / self.MODULUS
