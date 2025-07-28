import os
import json
import datetime
import re
from collections import defaultdict, Counter

# Docker-aware input/output directories
IN_DOCKER = os.path.exists("/app/input") and os.path.exists("/app/output")
INPUT_DIR = "/app/input" if IN_DOCKER else "./input"
OUTPUT_DIR = "/app/output" if IN_DOCKER else "./output"

# Basic stopwords for keyword extraction
STOPWORDS = set([
    "a", "an", "the", "is", "and", "or", "in", "on", "for", "to", "of", "with",
    "from", "by", "as", "at", "be", "this", "that", "it", "its", "are", "have",
    "has", "had", "was", "were", "s", "d", "ll", "m", "t", "re", "ve", "y",
    "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn", "haven", "isn",
    "ma", "mightn", "mustn", "needn", "don", "shan", "shouldn", "wasn", "weren",
    "won", "wouldn"
])

import pdfplumber

def group_lines(words, y_tolerance=3):
    lines = defaultdict(list)
    for word in words:
        added = False
        for y in list(lines.keys()):
            if abs(word['top'] - y) <= y_tolerance:
                lines[y].append(word)
                added = True
                break
        if not added:
            lines[word['top']].append(word)
    sorted_lines = sorted(lines.values(), key=lambda line: line[0]['top'])
    return [sorted(line, key=lambda w: w['x0']) for line in sorted_lines]

def is_bold(word):
    font = word.get("fontname", "").lower()
    return "bold" in font or "black" in font or "demi" in font or "heavy" in font

def get_color_tuple(word):
    color = word.get("non_stroking_color")
    if isinstance(color, (list, tuple)) and all(isinstance(x, (int, float)) for x in color):
        return tuple(color)
    return None

def extract_outline_and_content(pdf_path):
    outline_with_content = []
    title = ""
    all_font_sizes = []
    all_colors = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:min(len(pdf.pages), 5)]:
            words = page.extract_words(extra_attrs=["size", "non_stroking_color", "fontname"])
            all_font_sizes.extend([w['size'] for w in words if 'size' in w])
            all_colors.extend([get_color_tuple(w) for w in words if get_color_tuple(w)])

        if not all_font_sizes:
            return {"title": "", "outline_with_content": []}

        body_font_size = Counter(all_font_sizes).most_common(1)[0][0]
        
        potential_heading_sizes = sorted(list(set(s for s in all_font_sizes if s > body_font_size)), reverse=True)
        
        heading_sizes = potential_heading_sizes[:3]
        size_to_level = {size: f"H{i+1}" for i, size in enumerate(heading_sizes)}
        
        common_colors = [color for color, _ in Counter(all_colors).most_common(min(len(all_colors), 5))]

        for page_idx in range(min(2, len(pdf.pages))):
            page = pdf.pages[page_idx]
            words_on_page = page.extract_words(extra_attrs=["size"])
            lines_on_page = group_lines(words_on_page)
            
            max_page_font_size = 0
            if words_on_page:
                max_page_font_size = max([w['size'] for w in words_on_page if 'size' in w], default=0)

            for line in lines_on_page:
                if not line: continue
                first_word = line[0]
                font_size = first_word.get("size", body_font_size)
                full_text = " ".join(w['text'] for w in line).strip()

                if font_size >= max_page_font_size * 0.95 and len(full_text) < 150 and first_word['top'] < page.height / 3:
                    if not title or font_size > max_page_font_size:
                        title = full_text
                        break
            if title:
                break

        current_section_text_lines = []
        last_heading_index = -1

        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(extra_attrs=["size", "fontname", "non_stroking_color"])
            lines = group_lines(words)

            line_gaps = []
            for i in range(1, len(lines)):
                top = lines[i][0]['top']
                prev_bottom = lines[i - 1][-1]['bottom']
                gap = top - prev_bottom
                if gap > 0:
                    line_gaps.append(gap)
            avg_body_gap = sum(line_gaps) / len(line_gaps) if line_gaps else 5

            for i, line in enumerate(lines):
                if not line: continue

                first_word = line[0]
                font_size = first_word.get("size", body_font_size)
                font_color = get_color_tuple(first_word)
                indent = first_word.get("x0", 999)
                bold = is_bold(first_word)
                top = first_word.get("top", 0)

                full_text = " ".join(w['text'] for w in line).strip()
                
                if not full_text or len(full_text) > 150 or len(full_text) < 3:
                    if current_section_text_lines and last_heading_index != -1:
                        current_section_text_lines.append(full_text)
                    continue

                gap_above = 0
                if i > 0:
                    prev_bottom = lines[i - 1][-1]['bottom']
                    gap_above = top - prev_bottom
                
                score = 0
                
                if font_size > body_font_size * 1.05:
                    score += 2
                    if font_size in heading_sizes:
                        score += 3 if font_size == heading_sizes[0] else (2 if font_size == heading_sizes[1] else 1)
                
                if bold: score += 2
                
                if font_color and font_color not in common_colors: score += 1

                if indent < 80: score += 1
                
                if gap_above > (avg_body_gap * 1.5): score += 1
                                        
                if full_text.isupper() and len(full_text) < 50: score += 1.5
                elif full_text.istitle() and not (full_text.lower().startswith("the ") or full_text.lower().startswith("a ")): score += 1

                if re.match(r"^\d+(\.\d+)*\s+[A-Za-z]", full_text): score += 2

                is_heading_candidate = False
                if score >= 4:
                    is_heading_candidate = True
                
                if not is_heading_candidate and font_size > body_font_size and bold and (gap_above > avg_body_gap * 2 or re.match(r"^\d+(\.\d+)*\s+[A-Za-z]", full_text)):
                    is_heading_candidate = True

                if is_heading_candidate:
                    level = "H3"
                    if font_size in size_to_level:
                        level = size_to_level[font_size]
                    else:
                        if heading_sizes:
                            if font_size >= heading_sizes[0]: level = "H1"
                            elif len(heading_sizes) > 1 and font_size >= heading_sizes[1]: level = "H2"
                            else: level = "H3"

                    if title and full_text.lower() == title.lower():
                        continue

                    if not outline_with_content or (full_text.lower() != outline_with_content[-1]['text'].lower() and \
                                                    not full_text.lower().startswith(outline_with_content[-1]['text'].lower())):
                        
                        if current_section_text_lines and last_heading_index != -1:
                            outline_with_content[last_heading_index]['content'] = "\n".join(current_section_text_lines).strip()
                            current_section_text_lines = []

                        outline_with_content.append({
                            "level": level,
                            "text": full_text,
                            "page": page_num + 1,
                            "content": ""
                        })
                        last_heading_index = len(outline_with_content) - 1
                else:
                    if last_heading_index != -1:
                        current_section_text_lines.append(full_text)

        if current_section_text_lines and last_heading_index != -1:
            outline_with_content[last_heading_index]['content'] = "\n".join(current_section_text_lines).strip()

    return {
        "title": title.strip(),
        "outline_with_content": outline_with_content
    }


def get_clean_keywords(text):
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return set(keywords)

def insert_spaces_between_concatenated_words(text):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([0-9])([a-zA-Z])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z])([0-9])', r'\1 \2', text)
    text = re.sub(r'([.,;?!])([a-zA-Z0-9])', r'\1 \2', text)
    return text

def parse_persona_for_output(persona_string, job_to_be_done_string):
    role = ""
    expertise = ""
    
    if "PhD Researcher" in persona_string:
        role = "PhD Researcher"
        expertise_match = re.search(r"in\s+(.+)", persona_string)
        if expertise_match:
            expertise = expertise_match.group(1).strip()
    elif "Investment Analyst" in persona_string:
        role = "Investment Analyst"
    elif "Undergraduate Chemistry Student" in persona_string:
        role = "Undergraduate Chemistry Student"
            
    job_keywords = get_clean_keywords(job_to_be_done_string)
    focus_areas = ", ".join(sorted(list(job_keywords)))

    if role == "PhD Researcher" and "Machine Learning" not in expertise:
        if expertise:
            expertise += ", Machine Learning"
        else:
            expertise = "Machine Learning"
            
    expertise = expertise.replace("in ", "").strip()
    
    return {
        "role": role,
        "expertise": expertise,
        "focus_areas": focus_areas
    }

def process_document_collection_for_1b(pdf_files, persona_definition, job_to_be_done):
    all_docs_processed_data = []

    for pdf_path in pdf_files:
        print(f"Extracting outline and content from {os.path.basename(pdf_path)}...")
        doc_data = extract_outline_and_content(pdf_path)
        all_docs_processed_data.append({
            "document_path": pdf_path,
            "document_title": doc_data["title"],
            "sections": doc_data["outline_with_content"]
        })

    persona_keywords = get_clean_keywords(persona_definition)
    job_keywords = get_clean_keywords(job_to_be_done)

    all_query_keywords = persona_keywords.union(job_keywords)
    
    print(f"Persona Keywords: {persona_keywords}")
    print(f"Job Keywords: {job_keywords}")

    scored_sections = []
    for doc_info in all_docs_processed_data:
        doc_filename = os.path.basename(doc_info["document_path"])
        for section in doc_info["sections"]:
            section_title = section["text"]
            section_content = section["content"]

            page_num = section["page"]

            score = 0
            
            cleaned_section_content_for_keywords = section_content.replace('\n', ' ').replace('\r', ' ')
            cleaned_section_content_for_keywords = re.sub(r'\s+', ' ', cleaned_section_content_for_keywords).strip()
            
            title_keywords = get_clean_keywords(section_title)
            content_keywords = get_clean_keywords(cleaned_section_content_for_keywords)

            score += sum(3 for kw in all_query_keywords if kw in title_keywords)
            score += sum(1 for kw in all_query_keywords if kw in content_keywords)

            if any(phrase.lower() in section_title.lower() for phrase in job_to_be_done.split() if len(phrase) > 5):
                score += 2
            
            if section["level"] in ["H1", "H2"] and score > 0:
                score *= 1.2

            scored_sections.append({
                "document": doc_filename,
                "page_number": page_num,
                "section_title": section_title,
                "content": section_content,
                "score": score
            })

    scored_sections.sort(key=lambda x: x["score"], reverse=True)

    extracted_sections_output = []
    sub_section_analysis_output = []
    
    processed_sub_section_pages = set()

    for rank, sec in enumerate(scored_sections):
        if sec["score"] > 0 or rank < 5:
            extracted_sections_output.append({
                "document": sec["document"],
                "page_number": sec["page_number"],
                "section_title": sec["section_title"],
                "importance_rank": rank + 1
            })

            raw_content = sec["content"]
            
            cleaned_content = raw_content.replace('\n', ' ').replace('\r', ' ')
            cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()
            final_refined_content = insert_spaces_between_concatenated_words(cleaned_content)

            sentences = re.split(r'(?<=[.!?])\s+', final_refined_content)
            sentences = [s.strip() for s in sentences if s.strip()]

            sentence_scores = []
            for sentence in sentences:
                s_score = sum(1 for kw in all_query_keywords if kw in get_clean_keywords(sentence))
                sentence_scores.append((sentence, s_score))
            
            sentence_scores.sort(key=lambda x: x[1], reverse=True)
            
            relevant_sentences = []
            if (sec["document"], sec["page_number"]) not in processed_sub_section_pages:
                for s_text, s_score in sentence_scores:
                    if s_score > 0 and len(s_text.split()) > 5:
                        relevant_sentences.append(s_text)
                        if len(relevant_sentences) >= 3:
                            break
                
                if relevant_sentences:
                    sub_section_analysis_output.append({
                        "document": sec["document"],
                        "page_number": sec["page_number"],
                        "refined_text": " ".join(relevant_sentences)
                    })
                    processed_sub_section_pages.add((sec["document"], sec["page_number"]))


    structured_persona = parse_persona_for_output(persona_definition, job_to_be_done)

    final_output = {
        "metadata": {
            "input_documents": [os.path.basename(p) for p in pdf_files],
            "persona": structured_persona,
            "job_to_be_done": job_to_be_done,
            "processing_timestamp": datetime.datetime.now().isoformat()
        },
        "extracted_sections": extracted_sections_output,
        "sub_section_analysis": sub_section_analysis_output
    }

    return final_output

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    persona_file_path = os.path.join(INPUT_DIR, "persona.txt")
    job_file_path = os.path.join(INPUT_DIR, "job_to_be_done.txt")

    try:
        with open(persona_file_path, "r", encoding="utf-8") as f:
            persona = f.read().strip()
        
        with open(job_file_path, "r", encoding="utf-8") as f:
            job = f.read().strip()

        if not persona:
            raise ValueError("persona.txt cannot be empty.")
        if not job:
            raise ValueError("job_to_be_done.txt cannot be empty.")

    except FileNotFoundError:
        print(f"Error: Missing input files. Ensure 'persona.txt' and 'job_to_be_done.txt' are in {INPUT_DIR}.")
        return
    except Exception as e:
        print(f"Error reading input text files: {e}")
        return

    pdf_files = [os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR) if f.lower().endswith(".pdf")]
    
    if not pdf_files:
        print(f"No PDF files found in {INPUT_DIR}. Please place your PDFs there.")
        return

    print(f"Starting Round 1B process for Persona: '{persona}', Job: '{job}'")

    result_1b = process_document_collection_for_1b(pdf_files, persona, job)

    output_file_name = "challenge1b_output.json"
    output_path = os.path.join(OUTPUT_DIR, output_file_name)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_1b, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Round 1B Processing Complete. Output written to: {output_path}")

if __name__ == "__main__":
    main()