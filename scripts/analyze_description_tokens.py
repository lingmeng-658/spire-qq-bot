from collections import Counter

import jieba

from card_guess.cards import (
    load_game_cards,
    render_description,
)

def is_useful_token(token):
    return any(
        #token至少存在一个中文或英文字母
        char.isalpha() for char in token
    )


def main():
    jieba.load_userdict(
        "src/card_guess/resources/sts_user_dict.txt"
    )
    cards = load_game_cards("mixed")
    document_counts = Counter()
    token_counts = Counter()
    for card in cards:
        description = render_description(card)
        tokens = jieba.lcut(description)
        unique_tokens = set(
            token for token in tokens if is_useful_token(token)
        )
        document_counts.update(unique_tokens)
        token_counts.update(
            token.strip() for token in tokens if is_useful_token(token)
        )

    for token, count in document_counts.most_common(100):
        percentage = count / len(cards) * 100
        total_count = token_counts[token]

        print(
            f"{token}: "
            f"{count} 张卡，"
            f"占比 {percentage:.1f}%，"
            f"共出现 {total_count} 次"
        )

if __name__ == "__main__":
    main()
