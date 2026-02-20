"""
定点数抽象模块

提供统一的定点数运算接口，避免霰弹式修改。
只需修改 FRACTION_BITS 类变量即可更改全局精度。

使用方法：
    from core.fixed import fixed, FixedPoint
    
    # 创建定点数
    x = fixed(100.5)  # 从浮点数
    y = FixedPoint.from_int(200)  # 从整数
    
    # 运算
    z = x + y
    z = x * y
    z = x / y
    
    # 转换
    float_val = z.to_float()
    int_val = z.to_int()
    
    # 从配置文件加载精度
    FixedPoint.configure(fraction_bits=16)  # 或从 config.json 读取
"""

from dataclasses import dataclass
from typing import ClassVar, Union, overload


@dataclass(frozen=True)
class FixedPoint:
    """
    定点数抽象类
    
    使用 16.16 格式（可配置）：
    - 高 16 位：整数部分
    - 低 16 位：小数部分
    
    只需修改 FRACTION_BITS 即可全局更改精度。
    
    属性:
        raw (int): 内部存储的原始整数值
    
    类变量:
        FRACTION_BITS (int): 小数位数，默认 16
        SCALE (int): 缩放因子 = 2^FRACTION_BITS
        MAX_VALUE (int): 最大值
        MIN_VALUE (int): 最小值
    
    示例:
        >>> x = FixedPoint.from_float(3.14)
        >>> x.to_float()
        3.14
        >>> y = fixed(2.0)
        >>> (x + y).to_float()
        5.14
    """
    
    # ============ 单一配置点 ============
    # 只需修改这里即可更改全局精度
    FRACTION_BITS: ClassVar[int] = 16
    # ===================================
    
    SCALE: ClassVar[int] = 1 << 16  # 初始值，会被 configure 更新
    MAX_VALUE: ClassVar[int] = (1 << 31) - 1
    MIN_VALUE: ClassVar[int] = -(1 << 31)
    
    @classmethod
    def configure(cls, fraction_bits: int):
        """
        配置定点数精度
        
        Args:
            fraction_bits: 小数位数
        
        示例:
            >>> FixedPoint.configure(16)  # 16.16 格式
            >>> FixedPoint.configure(8)   # 24.8 格式
        """
        if fraction_bits < 1 or fraction_bits > 30:
            raise ValueError(f"fraction_bits must be 1-30, got {fraction_bits}")
        
        cls.FRACTION_BITS = fraction_bits
        cls.SCALE = 1 << fraction_bits
        print(f"[FixedPoint] 已配置: {32 - fraction_bits}.{fraction_bits} 格式, SCALE={cls.SCALE}")
    
    raw: int = 0
    
    def __post_init__(self):
        """验证范围"""
        if not self.MIN_VALUE <= self.raw <= self.MAX_VALUE:
            raise ValueError(f"FixedPoint value out of range: {self.raw}")
    
    # ============ 工厂方法 ============
    
    @classmethod
    def from_float(cls, value: float) -> 'FixedPoint':
        """
        从浮点数创建定点数
        
        Args:
            value: 浮点数值
        
        Returns:
            FixedPoint 实例
        
        示例:
            >>> FixedPoint.from_float(3.14).to_float()
            3.14
        """
        return cls(raw=int(value * cls.SCALE))
    
    @classmethod
    def from_int(cls, value: int) -> 'FixedPoint':
        """
        从整数创建定点数（整数部分）
        
        Args:
            value: 整数值
        
        Returns:
            FixedPoint 实例（小数部分为0）
        
        示例:
            >>> FixedPoint.from_int(100).to_float()
            100.0
        """
        return cls(raw=value << cls.FRACTION_BITS)
    
    @classmethod
    def from_raw(cls, raw: int) -> 'FixedPoint':
        """
        从原始值创建（用于反序列化）
        
        Args:
            raw: 原始整数值
        
        Returns:
            FixedPoint 实例
        """
        return cls(raw=raw)
    
    # ============ 转换方法 ============
    
    def to_float(self) -> float:
        """
        转换为浮点数
        
        Returns:
            浮点数值
        """
        return self.raw / self.SCALE
    
    def to_int(self) -> int:
        """
        转换为整数（截断小数部分）
        
        Returns:
            整数值
        """
        return self.raw >> self.FRACTION_BITS
    
    def round(self) -> int:
        """
        四舍五入到整数
        
        Returns:
            整数值
        """
        return (self.raw + (self.SCALE >> 1)) >> self.FRACTION_BITS
    
    # ============ 算术运算 ============
    
    def __add__(self, other: Union['FixedPoint', int, float]) -> 'FixedPoint':
        """加法"""
        if isinstance(other, FixedPoint):
            return FixedPoint(raw=self.raw + other.raw)
        elif isinstance(other, int):
            return FixedPoint(raw=self.raw + (other << self.FRACTION_BITS))
        elif isinstance(other, float):
            return FixedPoint(raw=self.raw + int(other * self.SCALE))
        return NotImplemented
    
    def __radd__(self, other: Union[int, float]) -> 'FixedPoint':
        """右加法"""
        return self.__add__(other)
    
    def __sub__(self, other: Union['FixedPoint', int, float]) -> 'FixedPoint':
        """减法"""
        if isinstance(other, FixedPoint):
            return FixedPoint(raw=self.raw - other.raw)
        elif isinstance(other, int):
            return FixedPoint(raw=self.raw - (other << self.FRACTION_BITS))
        elif isinstance(other, float):
            return FixedPoint(raw=self.raw - int(other * self.SCALE))
        return NotImplemented
    
    def __rsub__(self, other: Union[int, float]) -> 'FixedPoint':
        """右减法"""
        if isinstance(other, (int, float)):
            return fixed(other) - self
        return NotImplemented
    
    def __mul__(self, other: Union['FixedPoint', int, float]) -> 'FixedPoint':
        """
        乘法
        
        注意：两个定点数相乘需要右移 FRACTION_BITS
        """
        if isinstance(other, FixedPoint):
            return FixedPoint(raw=(self.raw * other.raw) >> self.FRACTION_BITS)
        elif isinstance(other, int):
            return FixedPoint(raw=self.raw * other)
        elif isinstance(other, float):
            return FixedPoint(raw=int(self.raw * other))
        return NotImplemented
    
    def __rmul__(self, other: Union[int, float]) -> 'FixedPoint':
        """右乘法"""
        return self.__mul__(other)
    
    def __truediv__(self, other: Union['FixedPoint', int, float]) -> 'FixedPoint':
        """
        除法
        
        注意：两个定点数相除需要先左移 FRACTION_BITS
        """
        if isinstance(other, FixedPoint):
            if other.raw == 0:
                raise ZeroDivisionError("FixedPoint division by zero")
            return FixedPoint(raw=(self.raw << self.FRACTION_BITS) // other.raw)
        elif isinstance(other, int):
            if other == 0:
                raise ZeroDivisionError("FixedPoint division by zero")
            return FixedPoint(raw=self.raw // other)
        elif isinstance(other, float):
            if other == 0:
                raise ZeroDivisionError("FixedPoint division by zero")
            return FixedPoint(raw=int(self.raw / other))
        return NotImplemented
    
    def __rtruediv__(self, other: Union[int, float]) -> 'FixedPoint':
        """右除法"""
        if isinstance(other, (int, float)):
            return fixed(other) / self
        return NotImplemented
    
    def __floordiv__(self, other: Union['FixedPoint', int]) -> 'FixedPoint':
        """整除"""
        if isinstance(other, FixedPoint):
            if other.raw == 0:
                raise ZeroDivisionError("FixedPoint division by zero")
            return FixedPoint(raw=self.raw // other.raw)
        elif isinstance(other, int):
            if other == 0:
                raise ZeroDivisionError("FixedPoint division by zero")
            return FixedPoint(raw=self.raw // other)
        return NotImplemented
    
    def __mod__(self, other: Union['FixedPoint', int]) -> 'FixedPoint':
        """取模"""
        if isinstance(other, FixedPoint):
            return FixedPoint(raw=self.raw % other.raw)
        elif isinstance(other, int):
            return FixedPoint(raw=self.raw % (other << self.FRACTION_BITS))
        return NotImplemented
    
    def __neg__(self) -> 'FixedPoint':
        """负号"""
        return FixedPoint(raw=-self.raw)
    
    def __abs__(self) -> 'FixedPoint':
        """绝对值"""
        return FixedPoint(raw=abs(self.raw))
    
    # ============ 比较运算 ============
    
    def __lt__(self, other: Union['FixedPoint', int, float]) -> bool:
        if isinstance(other, FixedPoint):
            return self.raw < other.raw
        return self.to_float() < other
    
    def __le__(self, other: Union['FixedPoint', int, float]) -> bool:
        if isinstance(other, FixedPoint):
            return self.raw <= other.raw
        return self.to_float() <= other
    
    def __gt__(self, other: Union['FixedPoint', int, float]) -> bool:
        if isinstance(other, FixedPoint):
            return self.raw > other.raw
        return self.to_float() > other
    
    def __ge__(self, other: Union['FixedPoint', int, float]) -> bool:
        if isinstance(other, FixedPoint):
            return self.raw >= other.raw
        return self.to_float() >= other
    
    # ============ 其他方法 ============
    
    def __repr__(self) -> str:
        return f"FixedPoint({self.to_float()})"
    
    def __str__(self) -> str:
        return str(self.to_float())
    
    def __hash__(self) -> int:
        return hash(self.raw)
    
    def __int__(self) -> int:
        return self.to_int()
    
    def __float__(self) -> float:
        return self.to_float()
    
    def clamp(self, min_val: 'FixedPoint', max_val: 'FixedPoint') -> 'FixedPoint':
        """
        限制在范围内
        
        Args:
            min_val: 最小值
            max_val: 最大值
        
        Returns:
            限制后的值
        """
        if self.raw < min_val.raw:
            return min_val
        if self.raw > max_val.raw:
            return max_val
        return self


# ============ 便捷函数 ============

def fixed(value: Union[float, int, 'FixedPoint']) -> FixedPoint:
    """
    创建定点数的便捷函数
    
    Args:
        value: 浮点数、整数或 FixedPoint
    
    Returns:
        FixedPoint 实例
    
    示例:
        >>> x = fixed(3.14)
        >>> y = fixed(100)
        >>> z = fixed(x)
    """
    if isinstance(value, FixedPoint):
        return value
    elif isinstance(value, float):
        return FixedPoint.from_float(value)
    elif isinstance(value, int):
        return FixedPoint.from_int(value)
    else:
        raise TypeError(f"Cannot convert {type(value)} to FixedPoint")


# ============ 预定义常量 ============

ZERO = FixedPoint.from_int(0)
ONE = FixedPoint.from_int(1)
HALF = FixedPoint.from_float(0.5)
