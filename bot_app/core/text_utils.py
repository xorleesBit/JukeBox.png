def declension(number: int, p1: str, p2: str, p3: str) -> str:
    """
    Возвращает правильную форму слова в зависимости от числа.
    :param number: Число
    :param p1: Форма для 1 (слово)
    :param p2: Форма для 2-4 (слова)
    :param p3: Форма для 5-0 (слов)
    """
    n = abs(number) % 100
    n1 = n % 10
    
    if 10 < n < 20:
        return p3
    if 1 < n1 < 5:
        return p2
    if n1 == 1:
        return p1
    
    return p3

def format_count(number: int, p1: str, p2: str, p3: str) -> str:
    """Возвращает строку вида '5 слов'"""
    return f"{number} {declension(number, p1, p2, p3)}"
