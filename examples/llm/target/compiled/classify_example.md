# Classify Example

This document demonstrates how to use the `classify()` filter to categorize content into predefined labels.

## Source Content

# Product Feedback Collection

## Customer Review #1
"I love the new interface! It's so much more intuitive than before. The dark mode is perfect for late-night coding sessions."

## Customer Review #2
"The app crashes frequently when I try to export large files. This is really frustrating and I'm considering switching to a competitor."

## Customer Review #3
"Great features, but the pricing is too high for what you get. I'd be willing to pay if there was a student discount."

## Customer Review #4
"Excellent customer support! They responded to my question within minutes and solved my issue completely."

## Customer Review #5
"The mobile app needs work. It's slow and missing key features that are available on desktop."

---

## Classification Results

### Sentiment Analysis
Each review classified by sentiment:

**Review #1**: positive

**Review #2**: negative

**Review #3**: negative

**Review #4**: positive

**Review #5**: negative

### Topic Classification
Classify reviews by primary topic:

**Review #1**: interface

**Review #2**: performance

**Review #3**: pricing

**Review #4**: support

**Review #5**: performance

### Multi-Label Classification
Classify reviews with multiple applicable labels:

**Review #1**: ['design', 'interface', 'features']

**Review #2**: ['performance']